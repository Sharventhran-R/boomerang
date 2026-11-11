// Notification Repository for Boomerang (Phase 9.6)
import 'package:flutter/foundation.dart';
import '../models/notification_model.dart';
import 'api_client.dart';
import 'auth_service.dart';

class NotificationRepository extends ChangeNotifier {
  static NotificationRepository _instance = NotificationRepository._internal();
  factory NotificationRepository({
    ApiClient? apiClient,
    AuthService? authService,
  }) {
    if (apiClient != null || authService != null) {
      return NotificationRepository._internal(apiClient, authService);
    }
    return _instance;
  }
  static NotificationRepository get instance => _instance;

  static void setInstanceForTesting(NotificationRepository repo) {
    _instance = repo;
  }

  ApiClient? _apiClient;
  AuthService? _authService;

  final List<NotificationItemModel> _notifications = [];
  int _unreadCount = 0;
  int _currentPage = 1;
  int _totalPages = 1;
  int _total = 0;
  bool _isLoading = false;
  bool _isLoadingMore = false;
  String? _errorMessage;
  bool _hasLoaded = false;
  bool _useMockMode = false;
  NotificationPreferenceModel? _preferences;

  NotificationRepository._internal([this._apiClient, this._authService]);

  ApiClient get apiClient => _apiClient ?? AuthService.instance.apiClient;
  AuthService get authService => _authService ?? AuthService.instance;

  List<NotificationItemModel> get notifications =>
      List.unmodifiable(_notifications);
  int get unreadCount => _unreadCount;
  int get currentPage => _currentPage;
  int get totalPages => _totalPages;
  int get total => _total;
  bool get isLoading => _isLoading;
  bool get isLoadingMore => _isLoadingMore;
  String? get errorMessage => _errorMessage;
  bool get hasLoaded => _hasLoaded;
  bool get hasMore => _currentPage < _totalPages;
  bool get isMockMode => _useMockMode;
  NotificationPreferenceModel? get preferences => _preferences;

  void configure({
    ApiClient? client,
    AuthService? auth,
    bool useMockMode = false,
  }) {
    if (client != null) _apiClient = client;
    if (auth != null) _authService = auth;
    _useMockMode = useMockMode;
    _hasLoaded = false;
    _notifications.clear();
    _unreadCount = 0;
    _errorMessage = null;
  }

  /// Clears in-memory notification cache upon user logout or account switch.
  void clearUserData() {
    _notifications.clear();
    _unreadCount = 0;
    _currentPage = 1;
    _totalPages = 1;
    _total = 0;
    _hasLoaded = false;
    _isLoading = false;
    _isLoadingMore = false;
    _errorMessage = null;
    _preferences = null;
    notifyListeners();
  }

  /// Fetches paginated in-app notifications.
  Future<void> fetchNotifications({
    bool refresh = false,
    bool? isRead,
    String? type,
    int pageSize = 20,
  }) async {
    if (_useMockMode) {
      _hasLoaded = true;
      notifyListeners();
      return;
    }

    if (!authService.isAuthenticated) {
      clearUserData();
      return;
    }

    if (refresh) {
      _isLoading = true;
      _errorMessage = null;
      notifyListeners();
    } else {
      if (_isLoading || _isLoadingMore || !hasMore) return;
      _isLoadingMore = true;
      notifyListeners();
    }

    final targetPage = refresh ? 1 : _currentPage + 1;
    final requestUserId = authService.currentUser?.id;

    try {
      final queryParams = <String, dynamic>{
        'page': targetPage,
        'page_size': pageSize,
      };
      if (isRead != null) queryParams['is_read'] = isRead;
      if (type != null && type.isNotEmpty) queryParams['type'] = type;

      final response = await apiClient.get(
        '/api/v1/notifications',
        queryParams: queryParams,
        authenticated: true,
      );

      // Discard stale async response if user logged out or switched account in-flight
      if (authService.currentUser?.id != requestUserId ||
          !authService.isAuthenticated) {
        return;
      }

      final listResponse = NotificationListResponse.fromJson(
        response as Map<String, dynamic>,
      );

      if (refresh) {
        _notifications.clear();
        _notifications.addAll(listResponse.items);
      } else {
        // Prevent duplicate IDs when appending
        final existingIds = _notifications.map((n) => n.id).toSet();
        for (final item in listResponse.items) {
          if (!existingIds.contains(item.id)) {
            _notifications.add(item);
          }
        }
      }

      _currentPage = listResponse.page;
      _totalPages = listResponse.totalPages;
      _total = listResponse.total;
      _unreadCount = listResponse.unreadCount;
      _hasLoaded = true;
      _errorMessage = null;
    } on ApiException catch (e) {
      _errorMessage = e.message;
    } on NetworkException catch (e) {
      _errorMessage = e.message;
    } catch (e) {
      _errorMessage = 'Failed to load notifications: $e';
    } finally {
      _isLoading = false;
      _isLoadingMore = false;
      notifyListeners();
    }
  }

  /// Fast aggregate unread badge counter.
  Future<int> fetchUnreadCount() async {
    if (_useMockMode || !authService.isAuthenticated) {
      return _unreadCount;
    }

    final requestUserId = authService.currentUser?.id;

    try {
      final response = await apiClient.get(
        '/api/v1/notifications/unread-count',
        authenticated: true,
      );

      // Discard stale response if session changed while in-flight
      if (authService.currentUser?.id != requestUserId ||
          !authService.isAuthenticated) {
        return _unreadCount;
      }

      final model = UnreadCountModel.fromJson(response as Map<String, dynamic>);
      _unreadCount = model.unreadCount;
      notifyListeners();
      return _unreadCount;
    } catch (_) {
      return _unreadCount;
    }
  }

  /// Marks an individual notification as read.
  Future<void> markAsRead(String notificationId) async {
    final index = _notifications.indexWhere((n) => n.id == notificationId);
    if (index != -1 && !_notifications[index].isRead) {
      _notifications[index] = _notifications[index].copyWith(
        isRead: true,
        readAt: DateTime.now(),
      );
      if (_unreadCount > 0) _unreadCount--;
      notifyListeners();
    }

    if (_useMockMode || !authService.isAuthenticated) return;

    try {
      final response = await apiClient.patch(
        '/api/v1/notifications/$notificationId/read',
        authenticated: true,
      );
      final updated = NotificationItemModel.fromJson(
        response as Map<String, dynamic>,
      );
      if (index != -1) {
        _notifications[index] = updated;
        notifyListeners();
      }
    } catch (e) {
      // Refresh count on failure
      fetchUnreadCount();
    }
  }

  /// Marks all unread notifications as read.
  Future<void> markAllAsRead() async {
    for (int i = 0; i < _notifications.length; i++) {
      if (!_notifications[i].isRead) {
        _notifications[i] = _notifications[i].copyWith(
          isRead: true,
          readAt: DateTime.now(),
        );
      }
    }
    _unreadCount = 0;
    notifyListeners();

    if (_useMockMode || !authService.isAuthenticated) return;

    try {
      await apiClient.patch(
        '/api/v1/notifications/read-all',
        authenticated: true,
      );
    } catch (e) {
      fetchUnreadCount();
    }
  }

  /// Retrieves user notification preferences, caching the result.
  Future<NotificationPreferenceModel> fetchPreferences() async {
    if (_useMockMode || !authService.isAuthenticated) {
      _preferences ??= NotificationPreferenceModel.defaultPreferences();
      return _preferences!;
    }

    final requestUserId = authService.currentUser?.id;

    try {
      final response = await apiClient.get(
        '/api/v1/notifications/preferences',
        authenticated: true,
      );

      // Discard stale response if session changed while in-flight
      if (authService.currentUser?.id != requestUserId ||
          !authService.isAuthenticated) {
        return _preferences ?? NotificationPreferenceModel.defaultPreferences();
      }

      _preferences = NotificationPreferenceModel.fromJson(
        response as Map<String, dynamic>,
      );
      notifyListeners();
      return _preferences!;
    } catch (e) {
      _preferences ??= NotificationPreferenceModel.defaultPreferences();
      return _preferences!;
    }
  }

  /// Updates user notification preferences.
  Future<NotificationPreferenceModel> updatePreferences(
    UpdateNotificationPreferenceRequest request,
  ) async {
    if (_useMockMode || !authService.isAuthenticated) {
      _preferences = NotificationPreferenceModel(
        pushEnabled: request.pushEnabled ?? _preferences?.pushEnabled ?? true,
        inAppEnabled:
            request.inAppEnabled ?? _preferences?.inAppEnabled ?? true,
        matchAlertsEnabled:
            request.matchAlertsEnabled ??
            _preferences?.matchAlertsEnabled ??
            true,
        matchMinScore:
            request.matchMinScore ?? _preferences?.matchMinScore ?? 75.0,
        matchHighPriorityOnly:
            request.matchHighPriorityOnly ??
            _preferences?.matchHighPriorityOnly ??
            false,
        recoveryUpdatesEnabled:
            request.recoveryUpdatesEnabled ??
            _preferences?.recoveryUpdatesEnabled ??
            true,
        reportStatusEnabled:
            request.reportStatusEnabled ??
            _preferences?.reportStatusEnabled ??
            true,
        quietHoursEnabled:
            request.quietHoursEnabled ??
            _preferences?.quietHoursEnabled ??
            false,
        quietHoursStart:
            request.quietHoursStart ?? _preferences?.quietHoursStart,
        quietHoursEnd: request.quietHoursEnd ?? _preferences?.quietHoursEnd,
        updatedAt: DateTime.now(),
      );
      notifyListeners();
      return _preferences!;
    }

    final response = await apiClient.patch(
      '/api/v1/notifications/preferences',
      body: request.toJson(),
      authenticated: true,
    );
    _preferences = NotificationPreferenceModel.fromJson(
      response as Map<String, dynamic>,
    );
    notifyListeners();
    return _preferences!;
  }

  /// Registers or rotates an FCM device token on the backend.
  Future<DeviceResponseModel?> registerDevice({
    required String deviceId,
    required String fcmToken,
    required DevicePlatform platform,
    String? deviceModel,
    String? appVersion,
  }) async {
    if (_useMockMode || !authService.isAuthenticated) return null;

    final request = RegisterDeviceRequest(
      deviceId: deviceId,
      fcmToken: fcmToken,
      platform: platform,
      deviceModel: deviceModel,
      appVersion: appVersion,
    );

    final response = await apiClient.post(
      '/api/v1/devices/register',
      body: request.toJson(),
      authenticated: true,
    );

    return DeviceResponseModel.fromJson(response as Map<String, dynamic>);
  }

  /// Deactivates a device token upon user logout.
  Future<void> deactivateDevice(String deviceId) async {
    if (_useMockMode || !authService.isAuthenticated) return;

    try {
      await apiClient.delete('/api/v1/devices/$deviceId', authenticated: true);
    } catch (_) {
      // Tolerant to offline/network failure on logout
    }
  }

  /// Helper to insert a notification into local feed on push receipt.
  void addReceivedNotification(NotificationItemModel notification) {
    final existingIndex = _notifications.indexWhere(
      (n) => n.id == notification.id,
    );
    if (existingIndex == -1) {
      _notifications.insert(0, notification);
      if (!notification.isRead) {
        _unreadCount++;
      }
      notifyListeners();
    }
  }

  /// Sets mock notifications directly for testing and offline development.
  void setMockNotifications(
    List<NotificationItemModel> list, {
    int? unreadCount,
  }) {
    _notifications.clear();
    _notifications.addAll(list);
    _unreadCount = unreadCount ?? list.where((n) => !n.isRead).length;
    _total = list.length;
    _totalPages = 1;
    _currentPage = 1;
    _hasLoaded = true;
    _isLoading = false;
    _isLoadingMore = false;
    _errorMessage = null;
    notifyListeners();
  }

  /// Sets mock preferences directly for testing.
  void setMockPreferences(NotificationPreferenceModel prefs) {
    _preferences = prefs;
    notifyListeners();
  }

  /// Helper to manually increment unread counter on push arrival.
  void incrementUnreadCount() {
    _unreadCount++;
    notifyListeners();
  }
}
