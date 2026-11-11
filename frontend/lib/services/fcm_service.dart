// Firebase Cloud Messaging Service for Boomerang (Phase 9.6)
import 'dart:io' show Platform;
import 'dart:math';
import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';
import '../models/notification_model.dart';
import 'auth_service.dart';
import 'firebase_options.dart';
import 'notification_repository.dart';

@pragma('vm:entry-point')
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {
  // Background isolate message handler
  try {
    if (Firebase.apps.isEmpty) {
      await Firebase.initializeApp(
        options: DefaultFirebaseOptions.currentPlatform,
      );
    }
  } catch (_) {
    // Non-fatal background error
  }
}

class FCMService {
  static FCMService _instance = FCMService._internal();
  factory FCMService({
    FirebaseMessaging? messaging,
    NotificationRepository? repository,
    AuthService? authService,
  }) {
    if (messaging != null || repository != null || authService != null) {
      return FCMService._internal(messaging, repository, authService);
    }
    return _instance;
  }
  static FCMService get instance => _instance;

  static void setInstanceForTesting(FCMService service) {
    _instance = service;
  }

  FirebaseMessaging? _messaging;
  NotificationRepository? _repository;
  AuthService? _authService;

  bool _isInitialized = false;
  String? _cachedFcmToken;
  String? _persistentDeviceId;
  String? _lastRegisteredToken;
  bool _mockMode = false;
  String? _vapidKey;

  bool get isInitialized => _isInitialized;
  String? get currentToken => _cachedFcmToken;
  String? get persistentDeviceId => _persistentDeviceId;
  bool get isMockMode => _mockMode;
  String? get currentVapidKey =>
      _vapidKey ??
      (const String.fromEnvironment('FIREBASE_VAPID_PUBLIC_KEY').isNotEmpty
          ? const String.fromEnvironment('FIREBASE_VAPID_PUBLIC_KEY')
          : const String.fromEnvironment('FIREBASE_VAPID_KEY'));

  FCMService._internal([this._messaging, this._repository, this._authService]);

  NotificationRepository get repository =>
      _repository ?? NotificationRepository.instance;
  AuthService get authService => _authService ?? AuthService.instance;

  void configureForTesting({
    bool mockMode = true,
    String? mockToken,
    String? mockDeviceId,
    String? vapidKey,
  }) {
    _mockMode = mockMode;
    _isInitialized = true;
    _cachedFcmToken = mockToken ?? 'mock_fcm_token_1234567890';
    _persistentDeviceId = mockDeviceId ?? 'test-device-uuid';
    _lastRegisteredToken = null;
    if (vapidKey != null) {
      _vapidKey = vapidKey;
    }
  }

  /// Initializes Firebase and configures message stream listeners.
  Future<void> initialize() async {
    if (_mockMode) return;
    if (_isInitialized) return;

    try {
      if (Firebase.apps.isEmpty) {
        await Firebase.initializeApp(
          options: DefaultFirebaseOptions.currentPlatform,
        );
      }
      _messaging = FirebaseMessaging.instance;

      // Register background handler
      if (!kIsWeb) {
        FirebaseMessaging.onBackgroundMessage(
          firebaseMessagingBackgroundHandler,
        );
      }

      // Configure foreground message stream
      FirebaseMessaging.onMessage.listen(_handleForegroundMessage);

      // Configure interaction on tap
      FirebaseMessaging.onMessageOpenedApp.listen(_handleNotificationOpenedApp);

      // Listen for token rotations
      // ignore: deprecated_member_use
      _messaging?.onTokenRefresh.listen((newToken) {
        _cachedFcmToken = newToken;
        if (authService.isAuthenticated) {
          registerDeviceWithBackend(token: newToken);
        }
      });

      _isInitialized = true;
    } catch (e) {
      if (kDebugMode) {
        debugPrint(
          'FCMService: Firebase initialization skipped/unavailable: $e',
        );
      }
      _isInitialized = false;
    }
  }

  /// Requests notification permissions and registers device if granted.
  Future<bool> requestPermissionAndRegister() async {
    if (_mockMode) return true;
    if (!_isInitialized || _messaging == null) {
      await initialize();
    }
    if (_messaging == null) return false;

    try {
      final settings = await _messaging!.requestPermission(
        alert: true,
        badge: true,
        sound: true,
      );

      final isAuthorized =
          settings.authorizationStatus == AuthorizationStatus.authorized ||
          settings.authorizationStatus == AuthorizationStatus.provisional;

      if (!isAuthorized) {
        if (kDebugMode) {
          debugPrint(
            'FCMService: Notification permission denied or not granted',
          );
        }
        return false;
      }

      // Retrieve FCM registration token
      final vapidKey = currentVapidKey;
      // ignore: deprecated_member_use
      final token = await _messaging!.getToken(
        vapidKey: (kIsWeb && vapidKey != null && vapidKey.isNotEmpty)
            ? vapidKey
            : null,
      );

      if (token != null && token.isNotEmpty) {
        _cachedFcmToken = token;
        if (authService.isAuthenticated) {
          await registerDeviceWithBackend(token: token);
        }
        return true;
      }
      return false;
    } catch (e) {
      if (kDebugMode) {
        debugPrint('FCMService: Failed to retrieve or register token: $e');
      }
      return false;
    }
  }

  /// Sends device identifier and FCM registration token to Phase 9.5 backend.
  Future<DeviceResponseModel?> registerDeviceWithBackend({
    String? token,
  }) async {
    final fcmToken = token ?? _cachedFcmToken;
    if (fcmToken == null || fcmToken.isEmpty) return null;
    if (!authService.isAuthenticated) return null;

    // Prevent duplicate registrations if token and user have not changed
    if (_lastRegisteredToken == fcmToken) {
      return null;
    }

    try {
      final deviceId = await _getOrCreateDeviceId();
      final platform = _resolvePlatform();

      final response = await repository.registerDevice(
        deviceId: deviceId,
        fcmToken: fcmToken,
        platform: platform,
        deviceModel: _resolveDeviceModel(),
        appVersion: '1.0.0',
      );

      _lastRegisteredToken = fcmToken;
      return response;
    } catch (e) {
      if (kDebugMode) {
        debugPrint('FCMService: Error registering device token: $e');
      }
      return null;
    }
  }

  /// Deactivates device upon user logout.
  Future<void> deactivateCurrentDevice() async {
    final deviceId = _persistentDeviceId;
    _lastRegisteredToken = null;
    if (deviceId == null) return;

    try {
      await repository.deactivateDevice(deviceId);
    } catch (_) {
      // Never block or throw during logout
    }
  }

  void _handleForegroundMessage(RemoteMessage message) {
    final data = message.data;
    if (data.containsKey('id') || data.containsKey('match_id')) {
      final item = NotificationItemModel(
        id:
            (data['id'] as String?) ??
            'push_${DateTime.now().millisecondsSinceEpoch}',
        type: (data['type'] as String?) ?? 'GENERAL',
        title:
            message.notification?.title ??
            (data['title'] as String?) ??
            'Alert',
        body: message.notification?.body ?? (data['body'] as String?) ?? '',
        data: Map<String, dynamic>.from(data),
        priority: (data['priority'] as String?) ?? 'DEFAULT',
        isRead: false,
        createdAt: DateTime.now(),
      );
      repository.addReceivedNotification(item);
    } else {
      repository.incrementUnreadCount();
    }
  }

  void handleForegroundMessageForTesting(RemoteMessage message) =>
      _handleForegroundMessage(message);

  Future<void> handleTokenRefreshForTesting(String newToken) async {
    _cachedFcmToken = newToken;
    if (authService.isAuthenticated) {
      await registerDeviceWithBackend(token: newToken);
    }
  }

  void _handleNotificationOpenedApp(RemoteMessage message) {
    // Refresh notifications feed on banner tap (Phase 9.6 scope)
    repository.fetchNotifications(refresh: true);
    repository.fetchUnreadCount();
  }

  DevicePlatform _resolvePlatform() {
    if (kIsWeb) return DevicePlatform.web;
    try {
      if (Platform.isIOS) return DevicePlatform.ios;
    } catch (_) {}
    return DevicePlatform.android;
  }

  String _resolveDeviceModel() {
    if (kIsWeb) return 'Web Browser';
    try {
      if (Platform.isAndroid) return 'Android Device';
      if (Platform.isIOS) return 'Apple Device';
    } catch (_) {}
    return 'Generic Device';
  }

  Future<String> _getOrCreateDeviceId() async {
    if (_persistentDeviceId != null && _persistentDeviceId!.isNotEmpty) {
      return _persistentDeviceId!;
    }

    try {
      const storage = FlutterSecureStorage();
      final stored = await storage.read(key: 'boomerang_device_id');
      if (stored != null && stored.isNotEmpty) {
        _persistentDeviceId = stored;
        return stored;
      }
    } catch (_) {}

    final randomPart = Random().nextInt(9999999);
    final generated =
        'device_${DateTime.now().millisecondsSinceEpoch}_$randomPart';
    _persistentDeviceId = generated;

    try {
      const storage = FlutterSecureStorage();
      await storage.write(key: 'boomerang_device_id', value: generated);
    } catch (_) {}

    return generated;
  }
}
