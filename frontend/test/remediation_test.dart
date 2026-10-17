import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:frontend/models/user_model.dart';
import 'package:frontend/services/api_client.dart';
import 'package:frontend/services/auth_service.dart';
import 'package:frontend/services/geocoding_service.dart';
import 'package:frontend/services/location_service.dart';
import 'package:frontend/services/map_config.dart';
import 'package:frontend/services/recovery_repository.dart';
import 'package:frontend/services/report_repository.dart';
import 'package:frontend/services/token_storage.dart';
import 'package:frontend/main.dart';
import 'package:frontend/theme.dart';
import 'package:frontend/ui/screens/home_screen.dart';
import 'package:frontend/ui/screens/login_screen.dart';
import 'package:frontend/ui/screens/main_nav_screen.dart';
import 'package:frontend/ui/screens/map_screen.dart';
import 'package:frontend/ui/screens/my_reports_screen.dart';
import 'package:frontend/ui/screens/profile_screen.dart';
import 'package:frontend/ui/screens/recovery_requests_screen.dart';
import 'package:frontend/ui/widgets/app_toast.dart';

class MockHttpClient extends http.BaseClient {
  Future<http.StreamedResponse> Function(http.BaseRequest request)? handler;

  MockHttpClient([this.handler]);

  @override
  Future<http.StreamedResponse> send(http.BaseRequest request) {
    if (handler != null) {
      return handler!(request);
    }
    return Future.value(
      http.StreamedResponse(
        Stream.value(utf8.encode('{}')),
        200,
        headers: {'content-type': 'application/json; charset=utf-8'},
      ),
    );
  }
}

http.StreamedResponse jsonResponse(dynamic body, {int statusCode = 200}) {
  final bytes = utf8.encode(jsonEncode(body));
  return http.StreamedResponse(
    Stream.value(bytes),
    statusCode,
    contentLength: bytes.length,
    headers: {'content-type': 'application/json; charset=utf-8'},
  );
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late MockHttpClient mockClient;
  late ApiClient apiClient;

  setUp(() {
    mockClient = MockHttpClient();
    apiClient = ApiClient(
      baseUrl: 'http://test-remediation.local',
      client: mockClient,
    );
    AuthService.setInstanceForTesting(
      AuthService(client: apiClient, storage: InMemoryTokenStorage()),
    );
    LocationService.instance.clearLocation();
  });

  tearDown(() {
    AuthService.instance.logout();
    LocationService.instance.clearLocation();
  });

  group('Step 1: Identity & Operational Summary Regression Tests', () {
    testWidgets(
      'Desktop sidebar displays authenticated user name and email instead of Alex Morgan',
      (WidgetTester tester) async {
        tester.view.physicalSize = const Size(1280, 800);
        tester.view.devicePixelRatio = 1.0;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);

        final user = UserModel(
          id: 'user-sai-uuid',
          email: 'sai@example.com',
          name: 'sai',
          createdAt: DateTime.now(),
        );
        AuthService.instance.setSessionForTesting(
          user: user,
          accessToken: 'fake-token',
        );

        await tester.pumpWidget(const MaterialApp(home: MainNavScreen()));
        await tester.pumpAndSettle();

        expect(find.text('sai'), findsWidgets);
        expect(find.text('sai@example.com'), findsOneWidget);
        expect(find.text('Alex Morgan'), findsNothing);
        expect(find.text('Verified Member'), findsNothing);
      },
    );

    testWidgets(
      'ProfileScreen displays zero counts for new user without reports or requests',
      (WidgetTester tester) async {
        final user = UserModel(
          id: 'user-fresh-uuid',
          email: 'fresh@example.com',
          name: 'Fresh User',
          createdAt: DateTime.now(),
        );
        AuthService.instance.setSessionForTesting(
          user: user,
          accessToken: 'fake-token',
        );

        ReportRepository.instance.configure(
          client: apiClient,
          auth: AuthService.instance,
        );
        RecoveryRepository.instance.configure(client: apiClient);

        await tester.pumpWidget(const MaterialApp(home: ProfileScreen()));
        await tester.pumpAndSettle();

        expect(find.text('Fresh User'), findsOneWidget);
        expect(find.textContaining('fresh@example.com'), findsOneWidget);

        expect(find.text('0 reports'), findsOneWidget);
        expect(find.text('0 requests'), findsOneWidget);
        expect(
          find.text('3 reports: 2 active missing, 1 resolved'),
          findsNothing,
        );
        expect(find.text('2 received, 1 sent'), findsNothing);
      },
    );

    testWidgets(
      'Live mode ReportRepository does not leak mock reports into userReports for authenticated user',
      (WidgetTester tester) async {
        final user = UserModel(
          id: 'authenticated-user-id',
          email: 'auth@test.com',
          name: 'Auth User',
          createdAt: DateTime.now(),
        );
        AuthService.instance.setSessionForTesting(
          user: user,
          accessToken: 'fake-token',
        );

        ReportRepository.instance.configure(
          client: apiClient,
          auth: AuthService.instance,
        );

        expect(ReportRepository.instance.userReports, isEmpty);
        expect(ReportRepository.instance.isMockMode, isFalse);
      },
    );

    testWidgets(
      'MyReportsScreen displays empty state when authenticated user has no reports',
      (WidgetTester tester) async {
        final user = UserModel(
          id: 'user-empty-uuid',
          email: 'empty@test.com',
          name: 'Empty User',
          createdAt: DateTime.now(),
        );
        AuthService.instance.setSessionForTesting(
          user: user,
          accessToken: 'fake-token',
        );

        ReportRepository.instance.configure(
          client: apiClient,
          auth: AuthService.instance,
        );

        await tester.pumpWidget(const MaterialApp(home: MyReportsScreen()));
        await tester.pumpAndSettle();

        expect(find.text('No reports matching this filter.'), findsOneWidget);
        expect(find.text('MacBook Pro 14 M2'), findsNothing);
      },
    );

    testWidgets(
      'RecoveryRequestsScreen displays empty state when user has no received or sent requests',
      (WidgetTester tester) async {
        final user = UserModel(
          id: 'user-empty-uuid',
          email: 'empty@test.com',
          name: 'Empty User',
          createdAt: DateTime.now(),
        );
        AuthService.instance.setSessionForTesting(
          user: user,
          accessToken: 'fake-token',
        );

        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/recovery-requests') {
            return jsonResponse({'items': [], 'total': 0});
          }
          return jsonResponse({}, statusCode: 404);
        };

        RecoveryRepository.instance.configure(client: apiClient);

        await tester.pumpWidget(
          const MaterialApp(home: RecoveryRequestsScreen()),
        );
        await tester.pumpAndSettle();

        expect(find.text('No received recovery requests'), findsOneWidget);
      },
    );
  });

  group('Step 2: Map Tile Configuration & Attribution Tests', () {
    test(
      'MapConfig tileUrl uses OpenStreetMap public raster tiles by default',
      () {
        expect(MapConfig.tileUrl, contains('tile.openstreetmap.org'));
        expect(MapConfig.tileUrl.contains('apiKey='), isFalse);
        expect(MapConfig.tileUrl.contains('access_token='), isFalse);
      },
    );

    test('MapConfig attribution credits OpenStreetMap', () {
      expect(MapConfig.attribution, '© OpenStreetMap contributors');
    });
  });

  group('Step 3: Geocoding & Location Selection Flow Tests', () {
    test(
      'GeocodingService parses Nominatim search response accurately',
      () async {
        final geocoding = GeocodingService(
          client: MockHttpClient((request) async {
            expect(request.url.host, 'nominatim.openstreetmap.org');
            expect(request.url.queryParameters['q'], 'Central Park');
            return jsonResponse([
              {
                'place_id': 12345,
                'display_name': 'Central Park, Manhattan, New York, USA',
                'lat': '40.785091',
                'lon': '-73.968285',
                'type': 'park',
              },
              {
                'place_id': 67890,
                'display_name': 'Central Park West, New York, USA',
                'lat': '40.780000',
                'lon': '-73.970000',
                'type': 'highway',
              },
            ]);
          }),
        );

        final results = await geocoding.searchPlaces('Central Park');
        expect(results.length, 2);
        expect(
          results.first.displayName,
          'Central Park, Manhattan, New York, USA',
        );
        expect(results.first.latitude, closeTo(40.785, 0.001));
        expect(results.first.longitude, closeTo(-73.968, 0.001));
      },
    );

    test('LocationService supports setting manual anchor and clearing', () {
      final loc = LocationService.instance;
      expect(loc.hasLocation, isFalse);

      loc.setManualLocation(
        latitude: 40.7128,
        longitude: -74.0060,
        label: 'New York City',
      );
      expect(loc.hasLocation, isTrue);
      expect(loc.currentLocation?.latitude, closeTo(40.7128, 0.0001));
      expect(loc.currentLocation?.longitude, closeTo(-74.0060, 0.0001));
      expect(loc.currentLocation?.label, 'New York City');

      loc.clearLocation();
      expect(loc.hasLocation, isFalse);
      expect(loc.currentLocation, isNull);
    });
  });

  group('Step 4: 5 km Geo Filtering Enforcement Tests', () {
    test(
      'ReportRepository constructs query with radius_km=5.0 and coordinates',
      () async {
        http.Request? capturedRequest;
        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports') {
            capturedRequest = request as http.Request;
            return jsonResponse({
              'items': [],
              'page': 1,
              'page_size': 50,
              'total': 0,
              'total_pages': 0,
            });
          }
          return jsonResponse({}, statusCode: 404);
        };

        ReportRepository.instance.configure(
          client: apiClient,
          auth: AuthService.instance,
        );

        await ReportRepository.instance.loadReports(
          latitude: 40.7128,
          longitude: -74.0060,
          radiusKm: 5.0,
        );

        expect(capturedRequest, isNotNull);
        final params = capturedRequest!.url.queryParameters;
        expect(params['latitude'], '40.7128');
        expect(params['longitude'], '-74.006');
        expect(params['radius_km'], '5.0');
        expect(params['sort'], 'distance');
      },
    );

    testWidgets(
      'HomeScreen prompts to select location when unanchored without silent unbounded queries',
      (WidgetTester tester) async {
        ReportRepository.instance.configure(
          client: apiClient,
          auth: AuthService.instance,
        );

        await tester.pumpWidget(const MaterialApp(home: HomeScreen()));
        await tester.pumpAndSettle();

        expect(find.text('Select Location'), findsWidgets);
        expect(find.text('Downtown Kyiv'), findsNothing);
      },
    );
  });

  group('Step 5: Global Notification System (AppToast) Tests', () {
    testWidgets(
      'AppToast renders floating toast with monochromatic style and neutral icon',
      (WidgetTester tester) async {
        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.darkTheme,
            home: Scaffold(
              body: Builder(
                builder: (context) => ElevatedButton(
                  onPressed: () {
                    AppToast.success(
                      context,
                      message: 'Test success notification.',
                      actionLabel: 'VIEW',
                      onAction: () {},
                    );
                  },
                  child: const Text('Show Toast'),
                ),
              ),
            ),
          ),
        );

        await tester.tap(find.text('Show Toast'));
        await tester.pump(); // Start animation
        await tester.pump(const Duration(milliseconds: 300));

        expect(find.text('Test success notification.'), findsOneWidget);
        expect(find.text('VIEW'), findsOneWidget);
        expect(find.byKey(const Key('toast_dismiss_button')), findsOneWidget);
        expect(find.byIcon(Icons.check_circle_outline), findsOneWidget);
      },
    );

    testWidgets('AppToast dismisses automatically after 3 seconds', (
      WidgetTester tester,
    ) async {
      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: Scaffold(
            body: Builder(
              builder: (context) => ElevatedButton(
                onPressed: () {
                  AppToast.info(
                    context,
                    message: 'Ephemeral message.',
                    duration: const Duration(seconds: 3),
                  );
                },
                child: const Text('Show Toast'),
              ),
            ),
          ),
        ),
      );

      await tester.tap(find.text('Show Toast'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));
      expect(find.text('Ephemeral message.'), findsOneWidget);

      // Advance timer past 3 seconds
      await tester.pump(const Duration(seconds: 4));
      await tester.pumpAndSettle();
      expect(find.text('Ephemeral message.'), findsNothing);
    });

    testWidgets(
      'AppToast manual dismiss button closes notification immediately',
      (WidgetTester tester) async {
        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.darkTheme,
            home: Scaffold(
              body: Builder(
                builder: (context) => ElevatedButton(
                  onPressed: () {
                    AppToast.info(context, message: 'Dismissible message.');
                  },
                  child: const Text('Show Toast'),
                ),
              ),
            ),
          ),
        );

        await tester.tap(find.text('Show Toast'));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 300));
        expect(find.text('Dismissible message.'), findsOneWidget);

        await tester.tap(find.byKey(const Key('toast_dismiss_button')));
        await tester.pumpAndSettle();
        expect(find.text('Dismissible message.'), findsNothing);
      },
    );

    testWidgets('AppToast action button executes callback and dismisses', (
      WidgetTester tester,
    ) async {
      bool actionTriggered = false;

      await tester.pumpWidget(
        MaterialApp(
          theme: AppTheme.darkTheme,
          home: Scaffold(
            body: Builder(
              builder: (context) => ElevatedButton(
                onPressed: () {
                  AppToast.show(
                    context,
                    message: 'Report created.',
                    actionLabel: 'VIEW',
                    onAction: () {
                      actionTriggered = true;
                    },
                  );
                },
                child: const Text('Show Toast'),
              ),
            ),
          ),
        ),
      );

      await tester.tap(find.text('Show Toast'));
      await tester.pump();
      await tester.pump(const Duration(milliseconds: 300));

      await tester.tap(find.byKey(const Key('toast_action_button')));
      await tester.pumpAndSettle();

      expect(actionTriggered, isTrue);
      expect(find.text('Report created.'), findsNothing);
    });

    testWidgets(
      'AppToast wraps long text without overflow on narrow 360px mobile viewport',
      (WidgetTester tester) async {
        tester.view.physicalSize = const Size(360, 640);
        tester.view.devicePixelRatio = 1.0;
        addTearDown(tester.view.resetPhysicalSize);
        addTearDown(tester.view.resetDevicePixelRatio);

        await tester.pumpWidget(
          MaterialApp(
            theme: AppTheme.darkTheme,
            home: Scaffold(
              body: Builder(
                builder: (context) => ElevatedButton(
                  onPressed: () {
                    AppToast.error(
                      context,
                      message:
                          'This is an exceptionally long error notification message designed to ensure that text wraps properly across multiple lines without causing any RenderFlex overflow exceptions on narrow mobile devices.',
                      actionLabel: 'RETRY ACTION',
                      onAction: () {},
                    );
                  },
                  child: const Text('Show Long Toast'),
                ),
              ),
            ),
          ),
        );

        await tester.tap(find.text('Show Long Toast'));
        await tester.pump();
        await tester.pump(const Duration(milliseconds: 300));

        expect(tester.takeException(), isNull);
        expect(find.textContaining('This is an exceptionally'), findsOneWidget);
        expect(find.text('RETRY ACTION'), findsOneWidget);
      },
    );
  });

  group('Step 6: Map Page Immediate Recentering & Anchor Sync Tests', () {
    testWidgets(
      'LocationService manual selection updates active anchor immediately and synchronizes with MapScreen',
      (WidgetTester tester) async {
        final loc = LocationService.instance;
        loc.clearLocation();

        ReportRepository.instance.configure(
          client: apiClient,
          auth: AuthService.instance,
        );

        await tester.pumpWidget(const MaterialApp(home: MapScreen()));
        await tester.pumpAndSettle();

        // Initially no anchor set
        expect(find.text('Select Location'), findsWidgets);

        // Set manual anchor (e.g. from search selection or GPS)
        loc.setManualLocation(
          latitude: 48.8566,
          longitude: 2.3522,
          label: 'Paris Center',
        );
        await tester.pumpAndSettle();

        // Label and active anchor must be updated immediately
        expect(find.text('Paris Center'), findsWidgets);
        expect(loc.currentLocation?.latitude, closeTo(48.8566, 0.0001));
        expect(loc.currentLocation?.longitude, closeTo(2.3522, 0.0001));

        // Clearing anchor removes selection without fallback to hardcoded Kyiv
        loc.clearLocation();
        await tester.pumpAndSettle();

        expect(find.text('Select Location'), findsWidgets);
        expect(find.text('Paris Center'), findsNothing);
      },
    );
  });

  group('Step 7: Startup Authentication Gate & Session Restoration Tests', () {
    testWidgets(
      'BoomerangApp displays LoginScreen on fresh launch when unauthenticated in production mode',
      (WidgetTester tester) async {
        // Ensure AuthService is initialized with empty credentials
        final storage = InMemoryTokenStorage();
        final auth = AuthService(client: apiClient, storage: storage);
        AuthService.setInstanceForTesting(auth);
        await auth.restoreSession();

        ReportRepository.instance.configure(client: apiClient, auth: auth);

        await tester.pumpWidget(const BoomerangApp());
        await tester.pumpAndSettle();

        // Should present LoginScreen, not MainNavScreen as Alex Morgan
        expect(find.byType(LoginScreen), findsOneWidget);
        expect(find.text('Welcome back'), findsOneWidget);
        expect(find.text('Alex Morgan'), findsNothing);
      },
    );

    testWidgets(
      'BoomerangApp restores authenticated session when valid credentials are present',
      (WidgetTester tester) async {
        final storage = InMemoryTokenStorage();
        await storage.saveTokens(
          accessToken: 'valid-test-access-token',
          refreshToken: 'valid-test-refresh-token',
        );

        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/users/me') {
            return jsonResponse({
              'id': 'restored-user-123',
              'name': 'Restored Operator',
              'email': 'restored@operator.io',
              'created_at': DateTime.now().toIso8601String(),
            });
          }
          if (request.url.path == '/api/v1/reports') {
            return jsonResponse({
              'items': [],
              'page': 1,
              'page_size': 50,
              'total': 0,
              'total_pages': 0,
            });
          }
          if (request.url.path == '/api/v1/recovery-requests') {
            return jsonResponse({
              'items': [],
              'page': 1,
              'page_size': 50,
              'total': 0,
              'total_pages': 0,
            });
          }
          return jsonResponse({}, statusCode: 404);
        };

        final auth = AuthService(client: apiClient, storage: storage);
        AuthService.setInstanceForTesting(auth);
        await auth.restoreSession();

        expect(auth.isAuthenticated, isTrue);
        expect(auth.currentUser?.name, 'Restored Operator');

        ReportRepository.instance.configure(client: apiClient, auth: auth);

        await tester.pumpWidget(const BoomerangApp());
        await tester.pumpAndSettle();

        expect(find.byType(MainNavScreen), findsOneWidget);
        expect(find.byType(LoginScreen), findsNothing);
      },
    );

    testWidgets(
      'Logging out transitions BoomerangApp back to LoginScreen and clears session',
      (WidgetTester tester) async {
        final user = UserModel(
          id: 'user-logout-test',
          name: 'Session User',
          email: 'session@test.org',
          createdAt: DateTime.now(),
        );
        AuthService.instance.setSessionForTesting(
          user: user,
          accessToken: 'test-token',
        );

        ReportRepository.instance.configure(
          client: apiClient,
          auth: AuthService.instance,
        );

        await tester.pumpWidget(const BoomerangApp());
        await tester.pumpAndSettle();

        expect(find.byType(MainNavScreen), findsOneWidget);

        // Perform logout
        await AuthService.instance.logout();
        await tester.pumpAndSettle();

        expect(find.byType(LoginScreen), findsOneWidget);
        expect(AuthService.instance.isAuthenticated, isFalse);
        expect(AuthService.instance.currentUser, isNull);
      },
    );
  });
}
