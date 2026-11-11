import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/models/notification_model.dart';
import 'package:frontend/models/user_model.dart';
import 'package:frontend/services/api_client.dart';
import 'package:frontend/services/auth_service.dart';
import 'package:frontend/services/fcm_service.dart';
import 'package:frontend/services/notification_repository.dart';
import 'package:frontend/theme.dart';
import 'package:frontend/ui/screens/notification_settings_screen.dart';
import 'package:frontend/ui/screens/notifications_screen.dart';
import 'package:frontend/ui/widgets/notification_badge_icon.dart';
import 'package:frontend/ui/widgets/notification_item_card.dart';

class MockApiClient extends ApiClient {
  final Map<String, dynamic> responses = {};
  final List<String> recordedCalls = [];
  dynamic lastRequestBody;
  bool shouldThrowOnDelete = false;

  MockApiClient() : super(baseUrl: 'http://mock-api.local');

  @override
  Future<dynamic> get(
    String path, {
    Map<String, dynamic>? queryParams,
    bool authenticated = true,
  }) async {
    recordedCalls.add('GET $path');
    if (responses.containsKey(path)) {
      return responses[path];
    }
    return {};
  }

  @override
  Future<dynamic> post(
    String path, {
    dynamic body,
    Map<String, dynamic>? queryParams,
    bool authenticated = true,
  }) async {
    recordedCalls.add('POST $path');
    lastRequestBody = body;
    if (responses.containsKey(path)) {
      return responses[path];
    }
    return {};
  }

  @override
  Future<dynamic> patch(
    String path, {
    dynamic body,
    Map<String, dynamic>? queryParams,
    bool authenticated = true,
  }) async {
    recordedCalls.add('PATCH $path');
    lastRequestBody = body;
    if (responses.containsKey(path)) {
      return responses[path];
    }
    return {};
  }

  @override
  Future<dynamic> delete(
    String path, {
    dynamic body,
    Map<String, dynamic>? queryParams,
    bool authenticated = true,
  }) async {
    recordedCalls.add('DELETE $path');
    if (shouldThrowOnDelete) {
      throw const ApiException(statusCode: 500, message: 'Server down');
    }
    if (responses.containsKey(path)) {
      return responses[path];
    }
    return {};
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late MockApiClient mockApiClient;
  late NotificationRepository repo;
  late FCMService fcmService;

  setUp(() {
    mockApiClient = MockApiClient();
    repo = NotificationRepository.instance;
    fcmService = FCMService.instance;

    repo.configure(client: mockApiClient, useMockMode: false);
    fcmService.configureForTesting(mockMode: true);

    // Setup dummy authenticated session
    AuthService.instance.setSessionForTesting(
      user: UserModel(
        id: 'user-uuid-1',
        name: 'Test Member',
        email: 'test@example.com',
        createdAt: DateTime.now(),
      ),
      accessToken: 'dummy-access-token',
    );
  });

  tearDown(() {
    repo.clearUserData();
  });

  // =========================================================================
  // 1. DATA LAYER TESTS
  // =========================================================================
  group('Phase 9.6 - Notification Data Models', () {
    test('NotificationItemModel deserializes and serializes correctly', () {
      final json = {
        'id': 'notif-1',
        'type': 'match_alert',
        'title': 'High-Confidence Match Found',
        'body': 'Your missing Silver Macbook was spotted.',
        'data': {'match_id': 'match-uuid-1'},
        'priority': 'HIGH',
        'is_read': false,
        'read_at': null,
        'created_at': '2026-11-10T10:00:00.000Z',
      };

      final item = NotificationItemModel.fromJson(json);

      expect(item.id, 'notif-1');
      expect(item.title, 'High-Confidence Match Found');
      expect(item.body, 'Your missing Silver Macbook was spotted.');
      expect(item.type, 'match_alert');
      expect(item.priority, 'HIGH');
      expect(item.isHighPriority, isTrue);
      expect(item.isRead, isFalse);
      expect(item.readAt, isNull);
      expect(item.data['match_id'], 'match-uuid-1');

      final copy = item.copyWith(isRead: true, readAt: DateTime.now());
      expect(copy.isRead, isTrue);
      expect(copy.readAt, isNotNull);

      final serialized = item.toJson();
      expect(serialized['id'], 'notif-1');
      expect(serialized['type'], 'match_alert');
    });

    test('NotificationListResponse deserializes correctly', () {
      final json = {
        'items': [
          {
            'id': 'notif-1',
            'type': 'match_alert',
            'title': 'Match Alert',
            'body': 'Item found nearby',
            'data': {},
            'priority': 'DEFAULT',
            'is_read': false,
            'read_at': null,
            'created_at': '2026-11-10T10:00:00.000Z',
          },
        ],
        'total': 1,
        'page': 1,
        'page_size': 20,
        'total_pages': 1,
        'unread_count': 1,
      };

      final res = NotificationListResponse.fromJson(json);
      expect(res.total, 1);
      expect(res.unreadCount, 1);
      expect(res.items.length, 1);
      expect(res.items.first.title, 'Match Alert');
    });

    test('UnreadCountModel deserializes correctly', () {
      final json = {'unread_count': 7};
      final model = UnreadCountModel.fromJson(json);
      expect(model.unreadCount, 7);
    });

    test('DevicePlatform serialization and deserialization', () {
      expect(DevicePlatform.android.toApiString(), 'ANDROID');
      expect(DevicePlatform.ios.toApiString(), 'IOS');
      expect(DevicePlatform.web.toApiString(), 'WEB');

      expect(DevicePlatform.fromApiString('ANDROID'), DevicePlatform.android);
      expect(DevicePlatform.fromApiString('iOS'), DevicePlatform.ios);
      expect(DevicePlatform.fromApiString('web'), DevicePlatform.web);
      expect(DevicePlatform.fromApiString('unknown'), DevicePlatform.android);
    });

    test('RegisterDeviceRequest serializes correctly', () {
      final req = RegisterDeviceRequest(
        deviceId: 'device-123',
        fcmToken: 'fcm-token-xyz',
        platform: DevicePlatform.android,
        deviceModel: 'Pixel 8',
        appVersion: '1.0.0',
      );

      final json = req.toJson();
      expect(json['device_id'], 'device-123');
      expect(json['fcm_token'], 'fcm-token-xyz');
      expect(json['platform'], 'ANDROID');
      expect(json['device_model'], 'Pixel 8');
      expect(json['app_version'], '1.0.0');
    });

    test('NotificationPreferenceModel handles defaults and updates', () {
      final defaults = NotificationPreferenceModel.defaultPreferences();
      expect(defaults.pushEnabled, isTrue);
      expect(defaults.inAppEnabled, isTrue);
      expect(defaults.matchAlertsEnabled, isTrue);
      expect(defaults.matchMinScore, 75.0);
      expect(defaults.quietHoursEnabled, isFalse);

      final updateReq = UpdateNotificationPreferenceRequest(
        pushEnabled: false,
        matchMinScore: 85.0,
        quietHoursEnabled: true,
        quietHoursStart: '23:00',
        quietHoursEnd: '07:00',
      );

      final json = updateReq.toJson();
      expect(json['push_enabled'], isFalse);
      expect(json['match_min_score'], 85.0);
      expect(json['quiet_hours_enabled'], isTrue);
      expect(json['quiet_hours_start'], '23:00');
      expect(json['quiet_hours_end'], '07:00');
      expect(json.containsKey('in_app_enabled'), isFalse);
    });
  });

  // =========================================================================
  // 2. NOTIFICATION REPOSITORY TESTS
  // =========================================================================
  group('Phase 9.6 - Notification Repository Operations', () {
    test('fetchNotifications updates state and pagination correctly', () async {
      mockApiClient.responses['/api/v1/notifications'] = {
        'items': [
          {
            'id': 'notif-1',
            'type': 'match_alert',
            'title': 'Alert 1',
            'body': 'Body 1',
            'data': {},
            'priority': 'HIGH',
            'is_read': false,
            'read_at': null,
            'created_at': '2026-11-10T10:00:00.000Z',
          },
        ],
        'total': 1,
        'page': 1,
        'page_size': 20,
        'total_pages': 1,
        'unread_count': 1,
      };

      await repo.fetchNotifications(refresh: true);

      expect(repo.notifications.length, 1);
      expect(repo.unreadCount, 1);
      expect(repo.hasLoaded, isTrue);
      expect(repo.errorMessage, isNull);
      expect(
        mockApiClient.recordedCalls,
        contains('GET /api/v1/notifications'),
      );
    });

    test('fetchUnreadCount updates unread counter', () async {
      mockApiClient.responses['/api/v1/notifications/unread-count'] = {
        'unread_count': 4,
      };

      final count = await repo.fetchUnreadCount();
      expect(count, 4);
      expect(repo.unreadCount, 4);
    });

    test(
      'markAsRead performs optimistic update and notifies backend',
      () async {
        repo.setMockNotifications([
          NotificationItemModel(
            id: 'item-10',
            title: 'Unread Alert',
            body: 'Content',
            type: 'match_alert',
            priority: 'DEFAULT',
            data: const {},
            isRead: false,
            readAt: null,
            createdAt: DateTime.now(),
          ),
        ], unreadCount: 1);

        mockApiClient.responses['/api/v1/notifications/item-10/read'] = {
          'id': 'item-10',
          'title': 'Unread Alert',
          'body': 'Content',
          'type': 'match_alert',
          'priority': 'DEFAULT',
          'data': {},
          'is_read': true,
          'read_at': DateTime.now().toIso8601String(),
          'created_at': DateTime.now().toIso8601String(),
        };

        await repo.markAsRead('item-10');

        expect(repo.notifications.first.isRead, isTrue);
        expect(repo.unreadCount, 0);
        expect(
          mockApiClient.recordedCalls,
          contains('PATCH /api/v1/notifications/item-10/read'),
        );
      },
    );

    test('markAllAsRead marks all notifications as read', () async {
      repo.setMockNotifications([
        NotificationItemModel(
          id: 'n-1',
          title: 'Alert 1',
          body: 'Body 1',
          type: 'match_alert',
          priority: 'DEFAULT',
          data: const {},
          isRead: false,
          readAt: null,
          createdAt: DateTime.now(),
        ),
        NotificationItemModel(
          id: 'n-2',
          title: 'Alert 2',
          body: 'Body 2',
          type: 'recovery_request',
          priority: 'HIGH',
          data: const {},
          isRead: false,
          readAt: null,
          createdAt: DateTime.now(),
        ),
      ], unreadCount: 2);

      await repo.markAllAsRead();

      expect(repo.unreadCount, 0);
      expect(repo.notifications.every((n) => n.isRead), isTrue);
      expect(
        mockApiClient.recordedCalls,
        contains('PATCH /api/v1/notifications/read-all'),
      );
    });

    test('clearUserData completely flushes in-memory cache on logout', () {
      repo.setMockNotifications([
        NotificationItemModel(
          id: 'temp-1',
          title: 'T',
          body: 'B',
          type: 'match_alert',
          priority: 'DEFAULT',
          data: const {},
          isRead: false,
          readAt: null,
          createdAt: DateTime.now(),
        ),
      ], unreadCount: 1);

      expect(repo.notifications.isNotEmpty, isTrue);
      expect(repo.unreadCount, 1);

      repo.clearUserData();

      expect(repo.notifications.isEmpty, isTrue);
      expect(repo.unreadCount, 0);
      expect(repo.hasLoaded, isFalse);
    });

    test(
      'registerDevice and deactivateDevice invoke proper endpoints',
      () async {
        mockApiClient.responses['/api/v1/devices/register'] = {
          'id': 'dev-uuid-1',
          'user_id': 'user-1',
          'device_id': 'client-dev-1',
          'platform': 'ANDROID',
          'fcm_token': 'fcm-abc',
          'device_model': 'Pixel 8',
          'app_version': '1.0.0',
          'is_active': true,
          'created_at': DateTime.now().toIso8601String(),
          'last_active_at': DateTime.now().toIso8601String(),
        };

        final device = await repo.registerDevice(
          deviceId: 'client-dev-1',
          fcmToken: 'fcm-abc',
          platform: DevicePlatform.android,
          deviceModel: 'Pixel 8',
          appVersion: '1.0.0',
        );

        expect(device, isNotNull);
        expect(device!.deviceId, 'client-dev-1');
        expect(
          mockApiClient.recordedCalls,
          contains('POST /api/v1/devices/register'),
        );

        await repo.deactivateDevice('client-dev-1');
        expect(
          mockApiClient.recordedCalls,
          contains('DELETE /api/v1/devices/client-dev-1'),
        );
      },
    );

    test(
      'stale async response from logged-out or previous user is discarded',
      () async {
        mockApiClient.responses['/api/v1/notifications'] = {
          'items': [
            {
              'id': 'stale-notif-1',
              'type': 'match_alert',
              'title': 'User A Secret Notification',
              'body': 'Confidential',
              'data': {},
              'priority': 'HIGH',
              'is_read': false,
              'read_at': null,
              'created_at': '2026-11-10T10:00:00.000Z',
            },
          ],
          'total': 1,
          'page': 1,
          'page_size': 20,
          'total_pages': 1,
          'unread_count': 1,
        };

        // Trigger fetch, but simulate user logging out before response is processed
        final fetchFuture = repo.fetchNotifications(refresh: true);
        AuthService.instance.setSessionForTesting(
          user: UserModel(
            id: 'user-uuid-2-different',
            name: 'Different Member',
            email: 'diff@example.com',
            createdAt: DateTime.now(),
          ),
          accessToken: 'diff-token',
        );

        await fetchFuture;

        // Stale items from user 1 must be rejected and not populate user 2's feed
        expect(repo.notifications.any((n) => n.id == 'stale-notif-1'), isFalse);
      },
    );

    test(
      'logout succeeds cleanly even if backend device deactivation throws',
      () async {
        // Simulate backend deactivation failure (e.g. 500 error or network disconnect)
        mockApiClient.shouldThrowOnDelete = true;

        // Logout must not throw and must still clear local auth & repository cache
        await expectLater(AuthService.instance.logout(), completes);
        expect(AuthService.instance.isAuthenticated, isFalse);
        expect(repo.notifications.isEmpty, isTrue);
        expect(repo.unreadCount, 0);
      },
    );
  });

  // =========================================================================
  // 3. FCM SERVICE TESTS
  // =========================================================================
  group('Phase 9.6 - FCM Service Lifecycle & Integration', () {
    test(
      'requestPermissionAndRegister succeeds in mock mode without throwing',
      () async {
        fcmService.configureForTesting(
          mockMode: true,
          mockToken: 'mock-fcm-token-555',
          mockDeviceId: 'test-device-uuid-999',
        );

        final success = await fcmService.requestPermissionAndRegister();
        expect(success, isTrue);
        expect(fcmService.currentToken, 'mock-fcm-token-555');
        expect(fcmService.persistentDeviceId, 'test-device-uuid-999');
      },
    );

    test('deactivateCurrentDevice triggers repository deactivation', () async {
      fcmService.configureForTesting(
        mockMode: true,
        mockDeviceId: 'device-to-deactivate',
      );

      await fcmService.deactivateCurrentDevice();
      expect(
        mockApiClient.recordedCalls,
        contains('DELETE /api/v1/devices/device-to-deactivate'),
      );
    });

    test('token rotation triggers backend device registration', () async {
      mockApiClient.responses['/api/v1/devices/register'] = {
        'id': 'dev-rotated',
        'user_id': 'user-1',
        'device_id': 'test-device-uuid-999',
        'platform': 'ANDROID',
        'fcm_token': 'new-rotated-token-888',
        'is_active': true,
        'created_at': DateTime.now().toIso8601String(),
        'last_active_at': DateTime.now().toIso8601String(),
      };

      await fcmService.handleTokenRefreshForTesting('new-rotated-token-888');

      expect(fcmService.currentToken, 'new-rotated-token-888');
      expect(
        mockApiClient.recordedCalls,
        contains('POST /api/v1/devices/register'),
      );
    });

    test(
      'handleForegroundMessage increments unread count and appends notification item',
      () {
        repo.setMockNotifications([], unreadCount: 1);

        fcmService.handleForegroundMessageForTesting(
          RemoteMessage(
            messageId: 'msg-fg-1',
            data: const {
              'id': 'notif-fg-100',
              'type': 'match_alert',
              'title': 'New Nearby Match',
              'body': 'Wallet spotted nearby',
              'priority': 'HIGH',
            },
          ),
        );

        expect(repo.unreadCount, 2);
        expect(repo.notifications.any((n) => n.id == 'notif-fg-100'), isTrue);
        expect(repo.notifications.first.title, 'New Nearby Match');
      },
    );

    test('web VAPID public key configuration resolves correctly', () {
      fcmService.configureForTesting(vapidKey: 'test-custom-public-vapid-key');

      expect(fcmService.currentVapidKey, 'test-custom-public-vapid-key');
    });
  });

  // =========================================================================
  // 4. UI WIDGET & SCREEN TESTS
  // =========================================================================
  group('Phase 9.6 - Notification UI & Widgets', () {
    testWidgets('NotificationBadgeIcon hides badge when unreadCount is 0', (
      tester,
    ) async {
      repo.setMockNotifications([], unreadCount: 0);

      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: NotificationBadgeIcon())),
      );

      expect(find.byType(NotificationBadgeIcon), findsOneWidget);
      expect(find.text('0'), findsNothing);
      expect(find.byIcon(Icons.notifications_outlined), findsOneWidget);
    });

    testWidgets('NotificationBadgeIcon displays badge with count when unread', (
      tester,
    ) async {
      repo.setMockNotifications([], unreadCount: 5);

      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: NotificationBadgeIcon())),
      );

      expect(find.text('5'), findsOneWidget);
      expect(find.byIcon(Icons.notifications_active_outlined), findsOneWidget);
    });

    testWidgets('NotificationBadgeIcon formats count above 99 as 99+', (
      tester,
    ) async {
      repo.setMockNotifications([], unreadCount: 150);

      await tester.pumpWidget(
        const MaterialApp(home: Scaffold(body: NotificationBadgeIcon())),
      );

      expect(find.text('99+'), findsOneWidget);
    });

    testWidgets(
      'NotificationItemCard renders title, body, and priority correctly',
      (tester) async {
        bool markedRead = false;
        final item = NotificationItemModel(
          id: 'card-test-1',
          title: 'High Match Alert: Laptop Found',
          body: 'A Macbook Pro with sticker was reported at Central Station.',
          type: 'match_alert',
          priority: 'high',
          data: const {'match_id': 'm-1'},
          isRead: false,
          readAt: null,
          createdAt: DateTime.now().subtract(const Duration(minutes: 5)),
        );

        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.darkTheme,
            home: Scaffold(
              body: NotificationItemCard(
                item: item,
                onMarkRead: () => markedRead = true,
              ),
            ),
          ),
        );

        expect(find.text('High Match Alert: Laptop Found'), findsOneWidget);
        expect(
          find.text(
            'A Macbook Pro with sticker was reported at Central Station.',
          ),
          findsOneWidget,
        );
        expect(find.text('HIGH PRIORITY'), findsOneWidget);
        expect(find.text('5m ago'), findsOneWidget);
        expect(find.text('Mark as read'), findsOneWidget);

        // Verify tapping triggers mark read without deep link navigation
        await tester.tap(find.text('Mark as read'));
        await tester.pumpAndSettle();
        expect(markedRead, isTrue);
      },
    );

    testWidgets(
      'NotificationsScreen displays empty state when no notifications',
      (tester) async {
        repo.setMockNotifications([], unreadCount: 0);

        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.darkTheme,
            home: const NotificationsScreen(),
          ),
        );
        await tester.pumpAndSettle();

        expect(find.text('Notifications'), findsOneWidget);
        expect(find.text('No notifications yet'), findsOneWidget);
        expect(find.byIcon(Icons.notifications_none_outlined), findsOneWidget);
      },
    );

    testWidgets(
      'NotificationsScreen displays list of notifications and filters',
      (tester) async {
        final now = DateTime.now();
        repo.setMockNotifications([
          NotificationItemModel(
            id: 'n-unread',
            title: 'Unread Notification 1',
            body: 'Details here',
            type: 'match_alert',
            priority: 'high',
            data: const {},
            isRead: false,
            readAt: null,
            createdAt: now,
          ),
          NotificationItemModel(
            id: 'n-read',
            title: 'Read Notification 2',
            body: 'Previous details',
            type: 'recovery_request',
            priority: 'normal',
            data: const {},
            isRead: true,
            readAt: now.subtract(const Duration(hours: 1)),
            createdAt: now.subtract(const Duration(hours: 1)),
          ),
        ], unreadCount: 1);

        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.darkTheme,
            home: const NotificationsScreen(),
          ),
        );
        await tester.pumpAndSettle();

        expect(find.text('Unread Notification 1'), findsOneWidget);
        expect(find.text('Read Notification 2'), findsOneWidget);
        expect(find.text('Unread (1)'), findsOneWidget);

        // Tap 'Unread (1)' filter chip
        await tester.tap(find.text('Unread (1)'));
        await tester.pumpAndSettle();

        expect(find.text('Unread Notification 1'), findsOneWidget);
        expect(find.text('Read Notification 2'), findsNothing);

        // Tap 'All' filter chip
        await tester.tap(find.text('All'));
        await tester.pumpAndSettle();

        expect(find.text('Unread Notification 1'), findsOneWidget);
        expect(find.text('Read Notification 2'), findsOneWidget);
      },
    );

    testWidgets(
      'NotificationSettingsScreen displays preferences and handles save',
      (tester) async {
        repo.setMockPreferences(
          NotificationPreferenceModel(
            pushEnabled: true,
            inAppEnabled: true,
            matchAlertsEnabled: true,
            matchMinScore: 80.0,
            matchHighPriorityOnly: false,
            recoveryUpdatesEnabled: true,
            reportStatusEnabled: true,
            quietHoursEnabled: true,
            quietHoursStart: '22:30',
            quietHoursEnd: '07:30',
            updatedAt: DateTime.now(),
          ),
        );

        mockApiClient.responses['/api/v1/notifications/preferences'] = {
          'push_enabled': true,
          'in_app_enabled': true,
          'match_alerts_enabled': true,
          'match_min_score': 80.0,
          'match_high_priority_only': false,
          'recovery_updates_enabled': true,
          'report_status_enabled': true,
          'quiet_hours_enabled': true,
          'quiet_hours_start': '22:30',
          'quiet_hours_end': '07:30',
          'updated_at': DateTime.now().toIso8601String(),
        };

        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.darkTheme,
            home: const NotificationSettingsScreen(),
          ),
        );
        await tester.pumpAndSettle();

        expect(find.text('Notification Settings'), findsOneWidget);
        expect(find.text('Push Notifications'), findsOneWidget);
        expect(find.text('In-App Notifications'), findsOneWidget);
        expect(find.text('Match Alerts'), findsOneWidget);
        expect(find.text('Minimum Match Score'), findsOneWidget);
        expect(find.text('80%'), findsOneWidget);
        expect(find.text('22:30'), findsOneWidget);
        expect(find.text('07:30'), findsOneWidget);
        expect(find.text('Save Preferences'), findsOneWidget);

        await tester.ensureVisible(find.text('Save Preferences'));
        await tester.pumpAndSettle();

        await tester.tap(find.text('Save Preferences'));
        await tester.pumpAndSettle();

        expect(
          mockApiClient.recordedCalls,
          contains('PATCH /api/v1/notifications/preferences'),
        );
      },
    );
  });
}
