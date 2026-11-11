// Automated Unit & Widget Test Suite for Phase 9.7: Deep Links & Push Notification Interactions
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/models/match_model.dart';
import 'package:frontend/models/notification_model.dart';
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
import 'package:frontend/ui/screens/recovery_requests_screen.dart';
import 'package:frontend/ui/screens/report_details_screen.dart';
import 'package:frontend/ui/widgets/notification_item_card.dart';

class MockApiClient extends ApiClient {
  final Map<String, dynamic> responses = {};
  final List<String> recordedCalls = [];

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
    id: 'user-auth-1',
    name: 'Test Navigator',
    email: 'nav@example.com',
    createdAt: DateTime.now(),
  );

  setUp(() {
    mockClient = MockApiClient();
    authService = AuthService.instance;
    notificationRepo = NotificationRepository.instance;
    fcmService = FCMService.instance;
    router = NotificationRouter.instance;

    // Reset and configure all singletons with offline mock dependencies
    router.resetForTesting();
    notificationRepo.configure(client: mockClient, useMockMode: true);
    ReportRepository.instance.resetToDefault();
    MatchRepository.instance.configure(client: mockClient, isMockMode: true);
    RecoveryRepository.instance.configure(client: mockClient);
    RecoveryRepository.instance.resetToMocks();
    fcmService.configureForTesting(mockMode: true);

    // Seed mock match details in MatchRepository for testing
    final mockMissing = ReportRepository.instance.getReportById('REP-001')!;
    final mockFound = ReportRepository.instance.getReportById('REP-008')!;
    final mockMatchDetail = MatchDetailModel(
      id: 'match-test-101',
      status: 'ACTIVE',
      compositeScore: 92.5,
      rawCompositeScore: 92.5,
      contradictionPenalty: 0.0,
      scoreIdentity: 95.0,
      scoreCharacteristics: 90.0,
      scoreDistance: 92.0,
      scoreTime: 93.0,
      classification: 'HIGH_PRIORITY',
      alertEligible: true,
      minimumEvidenceSatisfied: true,
      evidenceSummary: 'Strong brand and physical trait overlap',
      explainabilityDetails: {
        'identity': {'category_score': 40.0},
        'characteristics': {'has_contradiction': false},
        'distance': {'distance_meters': 400.0, 'distance_km': 0.4},
        'time': {'delta_hours': 1.0, 'delta_days': 0.04},
      },
      scoringVersion: 1,
      lastScoredAt: DateTime.now(),
      createdAt: DateTime.now(),
      updatedAt: DateTime.now(),
      reportMissing: mockMissing,
      reportFound: mockFound,
      userRole: 'MISSING',
    );

    MatchRepository.instance.setMockMatchDetail(
      'match-test-101',
      mockMatchDetail,
    );
    MatchRepository.instance.setMockMatchDetail(
      'match-dedup-123',
      mockMatchDetail,
    );
    MatchRepository.instance.setMockMatchDetail(
      'match-card-999',
      mockMatchDetail,
    );

    // Default to authenticated session
    authService.setSessionForTesting(
      user: testUser,
      accessToken: 'test-token-valid',
    );
  });

  tearDown(() {
    router.resetForTesting();
    notificationRepo.clearUserData();
  });

  // =========================================================================
  // 1. DESTINATION PARSING & URL SCHEMES (ALL 9 DOMAIN TYPES & URLS)
  // =========================================================================
  group('Phase 9.7 - Destination Parsing & URL Schemes', () {
    test('parses all 9 domain notification types correctly', () {
      // 1. MATCH_DETECTED
      final match1 = router.parseDestination(
        notificationType: 'MATCH_DETECTED',
        data: {'match_id': 'match-uuid-1'},
      );
      expect(match1.type, NotificationDestinationType.match);
      expect(match1.resourceId, 'match-uuid-1');

      // 2. MATCH_HIGH_PRIORITY
      final match2 = router.parseDestination(
        notificationType: 'MATCH_HIGH_PRIORITY',
        data: {'match_id': 'match-uuid-2'},
      );
      expect(match2.type, NotificationDestinationType.match);
      expect(match2.resourceId, 'match-uuid-2');

      // 3. MATCH_UPDATED
      final match3 = router.parseDestination(
        notificationType: 'MATCH_UPDATED',
        data: {'match_id': 'match-uuid-3'},
      );
      expect(match3.type, NotificationDestinationType.match);
      expect(match3.resourceId, 'match-uuid-3');

      // 4. RECOVERY_REQUEST_RECEIVED -> tab: received
      final rec1 = router.parseDestination(
        notificationType: 'RECOVERY_REQUEST_RECEIVED',
        data: {'recovery_request_id': 'req-uuid-1'},
      );
      expect(rec1.type, NotificationDestinationType.recovery);
      expect(rec1.resourceId, 'req-uuid-1');
      expect(rec1.tab, 'received');

      // 5. RECOVERY_REQUEST_ACCEPTED -> tab: sent
      final rec2 = router.parseDestination(
        notificationType: 'RECOVERY_REQUEST_ACCEPTED',
        data: {'recovery_request_id': 'req-uuid-2'},
      );
      expect(rec2.type, NotificationDestinationType.recovery);
      expect(rec2.resourceId, 'req-uuid-2');
      expect(rec2.tab, 'sent');

      // 6. RECOVERY_REQUEST_REJECTED -> tab: sent
      final rec3 = router.parseDestination(
        notificationType: 'RECOVERY_REQUEST_REJECTED',
        data: {'recovery_request_id': 'req-uuid-3'},
      );
      expect(rec3.type, NotificationDestinationType.recovery);
      expect(rec3.resourceId, 'req-uuid-3');
      expect(rec3.tab, 'sent');

      // 7. RECOVERY_REQUEST_COMPLETED with report_id -> report
      final rec4 = router.parseDestination(
        notificationType: 'RECOVERY_REQUEST_COMPLETED',
        data: {'report_id': 'rep-uuid-1', 'recovery_request_id': 'req-uuid-4'},
      );
      expect(rec4.type, NotificationDestinationType.report);
      expect(rec4.resourceId, 'rep-uuid-1');

      // 8. REPORT_STATUS_CHANGED -> report
      final rep1 = router.parseDestination(
        notificationType: 'REPORT_STATUS_CHANGED',
        data: {'report_id': 'rep-uuid-2'},
      );
      expect(rep1.type, NotificationDestinationType.report);
      expect(rep1.resourceId, 'rep-uuid-2');

      // 9. REPORT_EXPIRING -> report
      final rep2 = router.parseDestination(
        notificationType: 'REPORT_EXPIRING',
        data: {'report_id': 'rep-uuid-3'},
      );
      expect(rep2.type, NotificationDestinationType.report);
      expect(rep2.resourceId, 'rep-uuid-3');
    });

    test(
      'parses custom application URI schemes (boomerang://...) correctly',
      () {
        // Matches deep link
        final d1 = router.parseDestination(
          deepLink: 'boomerang://matches/match-deep-123',
        );
        expect(d1.type, NotificationDestinationType.match);
        expect(d1.resourceId, 'match-deep-123');

        // Reports deep link
        final d2 = router.parseDestination(
          deepLink: 'boomerang://reports/report-deep-456',
        );
        expect(d2.type, NotificationDestinationType.report);
        expect(d2.resourceId, 'report-deep-456');

        // Recovery requests deep link with tab and ID
        final d3 = router.parseDestination(
          deepLink: 'boomerang://recovery-requests?tab=sent&id=req-deep-789',
        );
        expect(d3.type, NotificationDestinationType.recovery);
        expect(d3.resourceId, 'req-deep-789');
        expect(d3.tab, 'sent');

        // Notifications deep link
        final d4 = router.parseDestination(
          deepLink: 'boomerang://notifications',
        );
        expect(d4.type, NotificationDestinationType.notifications);
      },
    );

    test('parses Web Push HTTPS URLs correctly', () {
      // Matches Web Push destination
      final w1 = router.parseDestination(
        deepLink: 'https://localhost:3000/matches/match-web-10',
      );
      expect(w1.type, NotificationDestinationType.match);
      expect(w1.resourceId, 'match-web-10');

      // Reports Web Push destination
      final w2 = router.parseDestination(
        deepLink: 'https://app.example.com/reports/report-web-20',
      );
      expect(w2.type, NotificationDestinationType.report);
      expect(w2.resourceId, 'report-web-20');

      // Recovery Web Push destination with query parameters
      final w3 = router.parseDestination(
        deepLink:
            'https://app.example.com/recovery-requests?tab=received&id=req-web-30',
      );
      expect(w3.type, NotificationDestinationType.recovery);
      expect(w3.resourceId, 'req-web-30');
      expect(w3.tab, 'received');

      // Notifications Web Push destination
      final w4 = router.parseDestination(
        deepLink: 'https://app.example.com/notifications',
      );
      expect(w4.type, NotificationDestinationType.notifications);
    });

    test('falls back to notifications screen on unknown or empty payload', () {
      final fallback1 = router.parseDestination();
      expect(fallback1.type, NotificationDestinationType.notifications);

      final fallback2 = router.parseDestination(
        notificationType: 'SYSTEM_ANNOUNCEMENT',
      );
      expect(fallback2.type, NotificationDestinationType.notifications);
    });
  });

  // =========================================================================
  // 2. DE-DUPLICATION & DEBOUNCING
  // =========================================================================
  group('Phase 9.7 - Debouncing and De-duplication', () {
    testWidgets('suppresses duplicate intent dispatched in rapid succession', (
      tester,
    ) async {
      await tester.pumpWidget(
        MaterialApp(
          navigatorKey: NotificationRouter.navigatorKey,
          theme: AppTheme.darkTheme,
          home: const Scaffold(body: Text('Initial Screen')),
        ),
      );

      final intent = NotificationRouteIntent(
        notificationId: 'notif-dedup-1',
        type: 'MATCH_DETECTED',
        data: {'match_id': 'match-dedup-123'},
      );

      // First route succeeds
      final firstResult = await router.routeIntent(intent);
      expect(firstResult, isTrue);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));

      expect(find.byType(MatchDetailScreen), findsOneWidget);

      // Rapid immediate second route with identical intent is suppressed
      final secondResult = await router.routeIntent(intent);
      expect(secondResult, isFalse);
    });
  });

  // =========================================================================
  // 3. AUTHENTICATION GATE & SESSION LIFECYCLE
  // =========================================================================
  group('Phase 9.7 - Authentication Gate and Pending Intent Lifecycle', () {
    testWidgets(
      'preserves pending intent when unauthenticated and executes on login',
      (tester) async {
        // Clear session to simulate unauthenticated launch
        authService.clearSessionForTesting();
        router.resetForTesting();

        await tester.pumpWidget(
          MaterialApp(
            navigatorKey: NotificationRouter.navigatorKey,
            theme: AppTheme.darkTheme,
            home: const Scaffold(body: Text('Login Screen Placeholder')),
          ),
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 100));

        final intent = NotificationRouteIntent(
          notificationId: 'notif-cold-1',
          type: 'REPORT_STATUS_CHANGED',
          data: {'report_id': 'REP-001'},
        );

        // 1. Trigger route while unauthenticated
        final routedBeforeAuth = await router.routeIntent(intent);
        expect(routedBeforeAuth, isFalse);
        expect(router.hasPendingRoute, isTrue);
        expect(router.pendingIntent?.notificationId, 'notif-cold-1');

        // Verify destination was NOT pushed
        expect(find.byType(ReportDetailsScreen), findsNothing);

        // 2. Simulate user authentication
        authService.setSessionForTesting(
          user: testUser,
          accessToken: 'valid-restored-token',
        );
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 300));

        // Verify pending route was processed and screen is now displayed
        expect(find.byType(ReportDetailsScreen), findsOneWidget);
        expect(router.hasPendingRoute, isFalse);
      },
    );

    test('clears pending route on explicit logout', () async {
      authService.clearSessionForTesting();
      router.resetForTesting();

      final intent = NotificationRouteIntent(
        notificationId: 'notif-logout-1',
        type: 'MATCH_DETECTED',
        data: {'match_id': 'match-target'},
      );

      // Queue intent
      final queued = await router.routeIntent(intent);
      expect(queued, isFalse);
      expect(router.hasPendingRoute, isTrue);

      // User logs out or switches account
      authService.clearSessionForTesting();
      expect(router.hasPendingRoute, isFalse);
      expect(router.pendingIntent, isNull);
    });
  });

  // =========================================================================
  // 4. WIDGET & NAVIGATION INTEGRATION
  // =========================================================================
  group('Phase 9.7 - Navigation Stack and Back-Stack Preservation', () {
    testWidgets('routes to MatchDetailScreen and preserves back navigation', (
      tester,
    ) async {
      await tester.pumpWidget(
        MaterialApp(
          navigatorKey: NotificationRouter.navigatorKey,
          theme: AppTheme.darkTheme,
          home: const Scaffold(body: Text('Root Screen')),
        ),
      );

      final intent = NotificationRouteIntent(
        notificationId: 'notif-nav-1',
        type: 'MATCH_DETECTED',
        data: {'match_id': 'match-test-101'},
      );

      final success = await router.routeIntent(intent);
      expect(success, isTrue);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));

      expect(find.byType(MatchDetailScreen), findsOneWidget);

      // Pop back to root
      final navigator = NotificationRouter.navigatorKey.currentState!;
      navigator.pop();
      await tester.pumpAndSettle();

      expect(find.byType(MatchDetailScreen), findsNothing);
      expect(find.text('Root Screen'), findsOneWidget);
    });

    testWidgets('routes to RecoveryRequestsScreen with initial tab correctly', (
      tester,
    ) async {
      await tester.pumpWidget(
        MaterialApp(
          navigatorKey: NotificationRouter.navigatorKey,
          theme: AppTheme.darkTheme,
          home: const Scaffold(body: Text('Root Screen')),
        ),
      );

      // Route with tab: 'sent'
      final intent = NotificationRouteIntent(
        notificationId: 'notif-rec-1',
        type: 'RECOVERY_REQUEST_ACCEPTED',
        data: {'recovery_request_id': 'rec-sent-202'},
      );

      final success = await router.routeIntent(intent);
      expect(success, isTrue);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));

      expect(find.byType(RecoveryRequestsScreen), findsOneWidget);
      final screen = tester.widget<RecoveryRequestsScreen>(
        find.byType(RecoveryRequestsScreen),
      );
      expect(screen.initialTab, 'sent');
      expect(screen.targetRequestId, 'rec-sent-202');
    });

    testWidgets(
      'identifies and highlights target recovery request when present',
      (tester) async {
        await tester.pumpWidget(
          MaterialApp(
            navigatorKey: NotificationRouter.navigatorKey,
            theme: AppTheme.darkTheme,
            home: const Scaffold(body: Text('Root Screen')),
          ),
        );

        // Route to default mock recovery request '#REQ-8941'
        final intent = NotificationRouteIntent(
          notificationId: 'notif-rec-target',
          type: 'RECOVERY_REQUEST_RECEIVED',
          data: {'recovery_request_id': '#REQ-8941'},
        );

        final success = await router.routeIntent(intent);
        expect(success, isTrue);
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 300));

        expect(find.byType(RecoveryRequestsScreen), findsOneWidget);
        expect(find.text('TARGETED'), findsOneWidget);
      },
    );

    testWidgets('handles missing or inaccessible recovery request gracefully', (
      tester,
    ) async {
      await tester.pumpWidget(
        MaterialApp(
          navigatorKey: NotificationRouter.navigatorKey,
          theme: AppTheme.darkTheme,
          home: const Scaffold(body: Text('Root Screen')),
        ),
      );

      // Route to non-existent recovery request
      final intent = NotificationRouteIntent(
        notificationId: 'notif-rec-missing',
        type: 'RECOVERY_REQUEST_RECEIVED',
        data: {'recovery_request_id': 'REQ-DOES-NOT-EXIST'},
      );

      final success = await router.routeIntent(intent);
      expect(success, isTrue);
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));

      expect(find.byType(RecoveryRequestsScreen), findsOneWidget);
      // TARGETED badge is NOT shown because ID does not match any request
      expect(find.text('TARGETED'), findsNothing);
      // Info feedback toast is surfaced
      expect(
        find.descendant(
          of: find.byType(RecoveryRequestsScreen),
          matching: find.text(
            'The requested recovery handover is no longer active or accessible.',
          ),
        ),
        findsOneWidget,
      );
    });

    testWidgets('in-app NotificationItemCard tap marks read and navigates', (
      tester,
    ) async {
      final notifItem = NotificationItemModel(
        id: 'card-tap-notif-1',
        type: 'MATCH_DETECTED',
        title: 'High Priority Match',
        body: 'A match was detected for your MacBook Pro',
        data: {'match_id': 'match-card-999'},
        priority: 'HIGH',
        isRead: false,
        createdAt: DateTime.now(),
      );

      notificationRepo.addReceivedNotification(notifItem);
      expect(notificationRepo.unreadCount, 1);

      await tester.pumpWidget(
        MaterialApp(
          navigatorKey: NotificationRouter.navigatorKey,
          theme: AppTheme.darkTheme,
          home: const NotificationsScreen(),
        ),
      );
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 200));

      expect(find.byType(NotificationItemCard), findsOneWidget);
      expect(find.text('High Priority Match'), findsOneWidget);

      // Tap card
      await tester.tap(find.byType(NotificationItemCard));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));

      // 1. Verify marked as read
      expect(notificationRepo.notifications.first.isRead, isTrue);

      // 2. Verify navigation to MatchDetailScreen
      expect(find.byType(MatchDetailScreen), findsOneWidget);

      // 3. Verify back button pops back to NotificationsScreen
      final navigator = NotificationRouter.navigatorKey.currentState!;
      navigator.pop();
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));

      expect(find.byType(NotificationsScreen), findsOneWidget);
    });

    testWidgets(
      'handles missing match_id safely with error toast without crash',
      (tester) async {
        await tester.pumpWidget(
          MaterialApp(
            navigatorKey: NotificationRouter.navigatorKey,
            theme: AppTheme.darkTheme,
            home: const Scaffold(body: Text('Base Screen')),
          ),
        );

        final intent = NotificationRouteIntent(
          notificationId: 'notif-missing-match-id',
          type: 'MATCH_DETECTED',
          data: {}, // Missing match_id
        );

        final success = await router.routeIntent(intent);
        expect(success, isFalse);
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 200));

        // Screen was NOT pushed and app did not crash
        expect(find.byType(MatchDetailScreen), findsNothing);
        expect(find.text('Base Screen'), findsOneWidget);
      },
    );

    testWidgets(
      'handles missing report_id safely with error toast without crash',
      (tester) async {
        await tester.pumpWidget(
          MaterialApp(
            navigatorKey: NotificationRouter.navigatorKey,
            theme: AppTheme.darkTheme,
            home: const Scaffold(body: Text('Base Screen')),
          ),
        );

        final intent = NotificationRouteIntent(
          notificationId: 'notif-missing-report-id',
          type: 'REPORT_STATUS_CHANGED',
          data: {}, // Missing report_id
        );

        final success = await router.routeIntent(intent);
        expect(success, isFalse);
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 200));

        // Screen was NOT pushed and app did not crash
        expect(find.byType(ReportDetailsScreen), findsNothing);
        expect(find.text('Base Screen'), findsOneWidget);
      },
    );

    testWidgets('handles unknown destination type gracefully', (tester) async {
      await tester.pumpWidget(
        MaterialApp(
          navigatorKey: NotificationRouter.navigatorKey,
          theme: AppTheme.darkTheme,
          home: const Scaffold(body: Text('Base Screen')),
        ),
      );

      final intent = NotificationRouteIntent(
        notificationId: 'notif-unknown',
        type: 'COMPLETELY_UNRECOGNIZED_TYPE',
        data: {},
      );

      // Parses as notifications fallback
      final destination = router.parseDestination(
        notificationType: intent.type,
      );
      expect(destination.type, NotificationDestinationType.notifications);
    });
  });

  // =========================================================================
  // 5. INTENT CONSTRUCTORS & SERIALIZATION
  // =========================================================================
  group('Phase 9.7 - NotificationRouteIntent Extraction Helpers', () {
    test('extracts intent correctly from raw Map data', () {
      final data = {
        'id': 'intent-map-1',
        'type': 'MATCH_HIGH_PRIORITY',
        'match_id': 'm-map-10',
        'deep_link': 'boomerang://matches/m-map-10',
      };
      final intent = NotificationRouteIntent.fromData(data);
      expect(intent.notificationId, 'intent-map-1');
      expect(intent.type, 'MATCH_HIGH_PRIORITY');
      expect(intent.deepLink, 'boomerang://matches/m-map-10');
      expect(intent.data['match_id'], 'm-map-10');
    });

    test('extracts intent correctly from Uri', () {
      final uri = Uri.parse(
        'https://app.example.com/reports/rep-uri-1?id=n-uri-1&type=REPORT_EXPIRING',
      );
      final intent = NotificationRouteIntent.fromUri(uri);
      expect(intent.notificationId, 'n-uri-1');
      expect(intent.type, 'REPORT_EXPIRING');
      expect(intent.deepLink, uri.toString());
    });
  });

  // =========================================================================
  // 6. FCM SERVICE INTERACTION INTEGRATION
  // =========================================================================
  group('Phase 9.7 - FCM Service Integration', () {
    test('checkInitialMessage returns null safely in mock mode', () async {
      final initial = await fcmService.checkInitialMessage();
      expect(initial, isNull);
    });

    test(
      'handleMessageOpenedApp forwards RemoteMessage to NotificationRouter',
      () {
        final remoteMessage = const RemoteMessage(
          data: {
            'type': 'REPORT_STATUS_CHANGED',
            'report_id': 'REP-001',
            'notification_id': 'notif-fcm-1',
          },
        );

        fcmService.handleMessageOpenedAppForTesting(remoteMessage);

        // Verify router parsed and attempted to route or saved pending
        expect(
          router.lastDispatchedKey != null || router.hasPendingRoute,
          isTrue,
        );
      },
    );
  });
}
