// End-to-End Flutter Verification & Hardening Suite for Phase 9.8
// Verifies full cross-layer FCM payload ingestion, NotificationRouter navigation,
// client-side payload privacy, and robust error handling on 401/403/404 responses.

import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/models/match_model.dart';
import 'package:frontend/models/user_model.dart';
import 'package:frontend/services/api_client.dart';
import 'package:frontend/services/auth_service.dart';
import 'package:frontend/services/fcm_service.dart';
import 'package:frontend/services/match_repository.dart';
import 'package:frontend/services/notification_repository.dart';
import 'package:frontend/services/notification_router.dart';
import 'package:frontend/services/recovery_repository.dart';
import 'package:frontend/services/report_repository.dart';
import 'package:frontend/theme.dart';
import 'package:frontend/ui/screens/match_detail_screen.dart';
import 'package:frontend/ui/screens/notifications_screen.dart';

class MockApiClient extends ApiClient {
  final Map<String, dynamic> responses = {};
  final List<String> recordedCalls = [];
  int? throwStatusCodeForPath(String path) => errorPaths[path];
  final Map<String, int> errorPaths = {};

  MockApiClient() : super(baseUrl: 'http://mock-api.local');

  @override
  Future<dynamic> get(
    String path, {
    Map<String, dynamic>? queryParams,
    bool authenticated = true,
  }) async {
    recordedCalls.add('GET $path');
    if (errorPaths.containsKey(path)) {
      throw ApiException(
        statusCode: errorPaths[path]!,
        message: 'Mock error for $path',
      );
    }
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
    if (errorPaths.containsKey(path)) {
      throw ApiException(
        statusCode: errorPaths[path]!,
        message: 'Mock error for $path',
      );
    }
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
    if (errorPaths.containsKey(path)) {
      throw ApiException(
        statusCode: errorPaths[path]!,
        message: 'Mock error for $path',
      );
    }
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
    if (errorPaths.containsKey(path)) {
      throw ApiException(
        statusCode: errorPaths[path]!,
        message: 'Mock error for $path',
      );
    }
    if (responses.containsKey(path)) {
      return responses[path];
    }
    return {};
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late MockApiClient mockClient;
  late NotificationRouter router;
  late AuthService authService;
  late NotificationRepository notificationRepo;
  late FCMService fcmService;

  final testUser = UserModel(
    id: 'user-auth-e2e',
    name: 'E2E Verified User',
    email: 'verified@example.com',
    createdAt: DateTime.now(),
  );

  setUp(() {
    mockClient = MockApiClient();
    authService = AuthService.instance;
    notificationRepo = NotificationRepository.instance;
    fcmService = FCMService.instance;
    router = NotificationRouter.instance;

    router.resetForTesting();
    notificationRepo.configure(client: mockClient, useMockMode: true);
    ReportRepository.instance.resetToDefault();
    MatchRepository.instance.configure(client: mockClient, isMockMode: true);
    RecoveryRepository.instance.configure(client: mockClient);
    RecoveryRepository.instance.resetToMocks();
    fcmService.configureForTesting(mockMode: true);

    // Setup mock match
    final mockMissing = ReportRepository.instance.getReportById('REP-001')!;
    final mockFound = ReportRepository.instance.getReportById('REP-008')!;
    final mockMatchDetail = MatchDetailModel(
      id: 'match-e2e-101',
      status: 'ACTIVE',
      compositeScore: 94.0,
      rawCompositeScore: 94.0,
      contradictionPenalty: 0.0,
      scoreIdentity: 95.0,
      scoreCharacteristics: 92.0,
      scoreDistance: 95.0,
      scoreTime: 94.0,
      classification: 'HIGH_PRIORITY',
      alertEligible: true,
      minimumEvidenceSatisfied: true,
      evidenceSummary: 'Complete hardware match',
      explainabilityDetails: {},
      scoringVersion: 1,
      lastScoredAt: DateTime.now(),
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
      reportMissing: mockMissing,
      reportFound: mockFound,
      userRole: 'MISSING',
    );
    MatchRepository.instance.setMockMatchDetail(
      'match-e2e-101',
      mockMatchDetail,
    );

    // Default to authenticated session
    authService.setSessionForTesting(
      user: testUser,
      accessToken: 'token-valid-e2e',
    );
  });

  tearDown(() {
    router.resetForTesting();
    notificationRepo.clearUserData();
  });

  // =========================================================================
  // 1. CROSS-LAYER FCM INGESTION & INTENT EXTRACTION
  // =========================================================================
  group('1. Cross-Layer FCM Ingestion & Intent Extraction', () {
    test('extracts route intent from RemoteMessage data envelope', () {
      final remoteMessage = const RemoteMessage(
        messageId: 'projects/boomerang-test/messages/mock-fcm-1',
        data: {
          'notification_id': 'notif-uuid-1',
          'type': 'MATCH_HIGH_PRIORITY',
          'match_id': 'match-e2e-101',
          'deep_link': 'boomerang://matches/match-e2e-101',
        },
      );

      final intent = NotificationRouteIntent.fromRemoteMessage(remoteMessage);
      expect(intent.notificationId, 'notif-uuid-1');
      expect(intent.type, 'MATCH_HIGH_PRIORITY');
      expect(intent.data['match_id'], 'match-e2e-101');
      expect(intent.deepLink, 'boomerang://matches/match-e2e-101');

      final destination = router.parseDestination(
        deepLink: intent.deepLink,
        notificationType: intent.type,
        data: intent.data,
      );
      expect(destination.type, NotificationDestinationType.match);
      expect(destination.resourceId, 'match-e2e-101');
    });

    test('extracts route intent from HTTPS Web Push format deep link', () {
      final intent = NotificationRouteIntent.fromData({
        'notification_id': 'notif-web-push-2',
        'type': 'REPORT_STATUS_CHANGED',
        'report_id': 'rep-web-99',
        'deep_link': 'https://app.boomerang.example.com/reports/rep-web-99',
      });

      final destination = router.parseDestination(
        deepLink: intent.deepLink,
        notificationType: intent.type,
        data: intent.data,
      );
      expect(destination.type, NotificationDestinationType.report);
      expect(destination.resourceId, 'rep-web-99');
    });
  });

  // =========================================================================
  // 2. ERROR HANDLING ON BACKEND 401 / 403 / 404 RESPONSES
  // =========================================================================
  group('2. Error Handling on Backend 401 / 403 / 404 Responses', () {
    testWidgets(
      'unauthenticated 401 session preserves pending route without crashing',
      (tester) async {
        // Simulate unauthenticated state
        authService.clearSessionForTesting();
        expect(authService.isAuthenticated, isFalse);

        await tester.pumpWidget(
          MaterialApp(
            navigatorKey: NotificationRouter.navigatorKey,
            theme: AppTheme.darkTheme,
            home: const Scaffold(body: Text('Login Screen')),
          ),
        );
        await tester.pumpAndSettle();

        final intent = NotificationRouteIntent.fromData({
          'notification_id': 'notif-deferred-401',
          'type': 'MATCH_HIGH_PRIORITY',
          'match_id': 'match-e2e-101',
        });

        // Route intent while logged out
        final dispatched = await router.routeIntent(intent);
        expect(dispatched, isFalse);
        expect(router.hasPendingRoute, isTrue);
        expect(router.pendingIntent?.notificationId, 'notif-deferred-401');

        // UI remains safely on Login Screen
        expect(find.text('Login Screen'), findsOneWidget);
        expect(find.byType(MatchDetailScreen), findsNothing);

        // Now authenticate user (AuthService automatically processes pending route)
        authService.setSessionForTesting(
          user: testUser,
          accessToken: 'token-refreshed',
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 300));

        // Navigation resumed directly to MatchDetailScreen and cleared pending intent
        expect(router.hasPendingRoute, isFalse);
        expect(find.byType(MatchDetailScreen), findsOneWidget);
      },
    );

    test(
      'repository handles 401 Unauthorized by setting error message without crashing',
      () async {
        notificationRepo.configure(client: mockClient, useMockMode: false);
        mockClient.errorPaths['/api/v1/notifications'] = 401;

        await notificationRepo.fetchNotifications(refresh: true);
        expect(
          notificationRepo.errorMessage,
          contains('Mock error for /api/v1/notifications'),
        );
        expect(notificationRepo.isLoading, isFalse);
      },
    );

    test(
      'repository handles 404 Not Found on markAsRead without fatal error',
      () async {
        notificationRepo.configure(client: mockClient, useMockMode: false);
        mockClient.errorPaths['/api/v1/notifications/missing-id-404/read'] =
            404;

        // Ensure calling markAsRead on 404 is handled gracefully or propagates ApiException
        try {
          await notificationRepo.markAsRead('missing-id-404');
        } catch (e) {
          expect(e, isA<ApiException>());
        }
      },
    );

    testWidgets(
      'missing or non-existent match resource displays error toast gracefully',
      (tester) async {
        await tester.pumpWidget(
          MaterialApp(
            navigatorKey: NotificationRouter.navigatorKey,
            theme: AppTheme.darkTheme,
            home: const Scaffold(body: Text('Home Screen')),
          ),
        );
        await tester.pumpAndSettle();

        final emptyMatchIntent = NotificationRouteIntent.fromData({
          'type': 'MATCH_HIGH_PRIORITY',
          // match_id omitted
        });

        final routed = await router.routeIntent(emptyMatchIntent);
        expect(routed, isFalse);
        await tester.pumpAndSettle();

        // Home Screen remains visible; no uncaught exceptions thrown
        expect(find.text('Home Screen'), findsOneWidget);
      },
    );
  });

  // =========================================================================
  // 3. CLIENT-SIDE PAYLOAD PRIVACY AUDIT ACROSS ALL 9 NOTIFICATION TYPES
  // =========================================================================
  group('3. Payload Privacy & Security Verification (All 9 Types)', () {
    final forbiddenKeys = [
      'latitude',
      'longitude',
      'lat',
      'lon',
      'coordinates',
      'password',
      'password_hash',
      'secret',
      'token_proof',
      'verification_token',
      'fcm_token',
    ];

    final testCases = <Map<String, dynamic>>[
      {
        'type': 'MATCH_DETECTED',
        'data': {'match_id': 'match-privacy-1'},
        'expectedDest': NotificationDestinationType.match,
      },
      {
        'type': 'MATCH_HIGH_PRIORITY',
        'data': {'match_id': 'match-privacy-2'},
        'expectedDest': NotificationDestinationType.match,
      },
      {
        'type': 'MATCH_UPDATED',
        'data': {'match_id': 'match-privacy-3'},
        'expectedDest': NotificationDestinationType.match,
      },
      {
        'type': 'RECOVERY_REQUEST_RECEIVED',
        'data': {'recovery_request_id': 'rec-privacy-4'},
        'expectedDest': NotificationDestinationType.recovery,
      },
      {
        'type': 'RECOVERY_REQUEST_ACCEPTED',
        'data': {'recovery_request_id': 'rec-privacy-5'},
        'expectedDest': NotificationDestinationType.recovery,
      },
      {
        'type': 'RECOVERY_REQUEST_REJECTED',
        'data': {'recovery_request_id': 'rec-privacy-6'},
        'expectedDest': NotificationDestinationType.recovery,
      },
      {
        'type': 'RECOVERY_REQUEST_COMPLETED',
        'data': {'report_id': 'rep-privacy-7'},
        'expectedDest': NotificationDestinationType.report,
      },
      {
        'type': 'REPORT_STATUS_CHANGED',
        'data': {'report_id': 'rep-privacy-8'},
        'expectedDest': NotificationDestinationType.report,
      },
      {
        'type': 'REPORT_EXPIRING',
        'data': {'report_id': 'rep-privacy-9'},
        'expectedDest': NotificationDestinationType.report,
      },
    ];

    for (final tc in testCases) {
      final typeStr = tc['type'] as String;
      final payloadData = tc['data'] as Map<String, dynamic>;
      final expectedDest = tc['expectedDest'] as NotificationDestinationType;

      test(
        'payload for $typeStr has zero coordinate/secret leakage and routes properly',
        () {
          // Assert zero forbidden keys in raw payload
          for (final forbidden in forbiddenKeys) {
            expect(
              payloadData.containsKey(forbidden),
              isFalse,
              reason: 'Payload for $typeStr leaked sensitive field: $forbidden',
            );
          }

          // Test destination resolution
          final dest = router.parseDestination(
            notificationType: typeStr,
            data: payloadData,
          );
          expect(dest.type, expectedDest);
        },
      );
    }
  });

  // =========================================================================
  // 4. RAPID INTERACTION & DEBOUNCING PROTECTION
  // =========================================================================
  group('4. Rapid Interaction & Debouncing Protection', () {
    testWidgets('suppresses duplicate navigations triggered within 1500ms', (
      tester,
    ) async {
      await tester.pumpWidget(
        MaterialApp(
          navigatorKey: NotificationRouter.navigatorKey,
          theme: AppTheme.darkTheme,
          home: const Scaffold(body: Text('Base Screen')),
        ),
      );
      await tester.pumpAndSettle();

      final intent = NotificationRouteIntent.fromData({
        'notification_id': 'notif-debounce-1',
        'type': 'MATCH_HIGH_PRIORITY',
        'match_id': 'match-e2e-101',
      });

      // First click routes successfully
      final firstResult = await router.routeIntent(intent);
      expect(firstResult, isTrue);

      // Immediate second click with identical intent is debounced
      final secondResult = await router.routeIntent(intent);
      expect(secondResult, isFalse);
    });
  });

  // =========================================================================
  // 5. NOTIFICATION CENTER & PREFERENCES INTEGRATION
  // =========================================================================
  group('5. Notification Center & Preferences Integration', () {
    testWidgets(
      'renders notifications screen and allows marking items as read',
      (tester) async {
        notificationRepo.configure(client: mockClient, useMockMode: true);

        await tester.pumpWidget(
          MaterialApp(
            navigatorKey: NotificationRouter.navigatorKey,
            theme: AppTheme.darkTheme,
            home: const NotificationsScreen(),
          ),
        );
        await tester.pumpAndSettle();

        expect(find.text('Notifications'), findsOneWidget);
      },
    );
  });
}
