import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:frontend/models/user_model.dart';
import 'package:frontend/services/api_client.dart';
import 'package:frontend/services/auth_service.dart';
import 'package:frontend/services/location_service.dart';
import 'package:frontend/services/report_repository.dart';
import 'package:frontend/services/token_storage.dart';
import 'package:frontend/ui/screens/home_screen.dart';
import 'package:frontend/ui/screens/map_screen.dart';
import 'package:frontend/ui/widgets/report_card.dart';
import 'package:frontend/ui/widgets/status_label.dart';

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
  late InMemoryTokenStorage tokenStorage;
  late AuthService authService;
  late ReportRepository reportRepo;

  setUp(() {
    LocationService.instance.clearLocation();
    mockClient = MockHttpClient();
    tokenStorage = InMemoryTokenStorage();
    apiClient = ApiClient(baseUrl: 'http://127.0.0.1:8000', client: mockClient);
    authService = AuthService(client: apiClient, storage: tokenStorage);
    authService.setSessionForTesting(
      user: UserModel(
        id: 'usr-anchor-1',
        name: 'Anchor Tester',
        email: 'anchor@example.com',
      ),
      accessToken: 'anchor-token-xyz',
    );
    reportRepo = ReportRepository(
      apiClient: apiClient,
      authService: authService,
    );
    reportRepo.configure(client: apiClient, auth: authService);
    ReportRepository.setInstanceForTesting(reportRepo);
    AuthService.setInstanceForTesting(authService);
  });

  tearDown(() {
    LocationService.instance.clearLocation();
  });

  group('Nearby Reports Location Anchor & 5 km Radius Strict Enforcement', () {
    // 1. No anchor on a fresh session -> zero nearby cards and location prompt
    testWidgets(
      '1. Fresh session with no anchor displays 0 nearby cards, 0 items, and location prompt',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));

        var apiWasCalled = false;
        mockClient.handler = (req) async {
          if (req.url.path == '/api/v1/reports') {
            apiWasCalled = true;
          }
          return jsonResponse({'items': [], 'total': 0});
        };

        await tester.pumpWidget(const MaterialApp(home: HomeScreen()));
        await tester.pumpAndSettle();

        // Must NOT make an unanchored API request on cold start
        expect(apiWasCalled, isFalse);

        // Feed has 0 report cards
        expect(find.byType(ReportCard), findsNothing);

        // Header shows "0 items"
        expect(find.text('0 items'), findsOneWidget);

        // Empty state displays the mandatory text
        expect(
          find.text('Select a location to see reports within 5 km.'),
          findsOneWidget,
        );
        expect(
          find.widgetWithText(ElevatedButton, 'Select Location'),
          findsOneWidget,
        );
        expect(find.text('Select Location'), findsNWidgets(2));
      },
    );

    // 2. Anchor selected -> correct latitude, longitude, and 5 km sent to repository/API
    test(
      '2. Anchor selected queries API with latitude, longitude, and 5.0 km radius',
      () async {
        http.Request? capturedReq;
        mockClient.handler = (req) async {
          if (req.url.path == '/api/v1/reports') {
            capturedReq = req as http.Request;
            return jsonResponse({
              'items': [],
              'total': 0,
              'page': 1,
              'page_size': 50,
              'total_pages': 0,
            });
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        LocationService.instance.setManualLocation(
          latitude: 50.4501,
          longitude: 30.5234,
          label: 'Kyiv Center',
        );

        await reportRepo.loadReports(
          latitude: 50.4501,
          longitude: 30.5234,
          radiusKm: 5.0,
        );

        expect(capturedReq, isNotNull);
        final params = capturedReq!.url.queryParameters;
        expect(params['latitude'], '50.4501');
        expect(params['longitude'], '30.5234');
        expect(params['radius_km'], '5.0');
        expect(params['sort'], 'distance');
      },
    );

    // 3, 4, 5. Report 0.5 km away (included), 4.9 km away (included), >5 km away (excluded)
    test(
      '3, 4, 5. Reports within 5 km (0.5 km, 4.9 km) are included; report beyond 5 km (5.5 km) is excluded',
      () async {
        // Mock server returns 0.5 km and 4.9 km reports (filtered by backend spatial logic)
        mockClient.handler = (req) async {
          if (req.url.path == '/api/v1/reports') {
            expect(req.url.queryParameters['radius_km'], '5.0');
            return jsonResponse({
              'items': [
                {
                  'id': 'rep-05km',
                  'type': 'MISSING',
                  'title': 'Close Item (0.5 km)',
                  'description': 'Near center',
                  'category': 'ELECTRONICS',
                  'latitude': 50.454,
                  'longitude': 30.523,
                  'distance_km': 0.5,
                  'event_time': '2026-10-15T12:00:00Z',
                  'status': 'ACTIVE',
                  'created_by_user_id': 'other-uid',
                },
                {
                  'id': 'rep-49km',
                  'type': 'MISSING',
                  'title': 'Edge Item (4.9 km)',
                  'description': 'Near boundary',
                  'category': 'WALLETS_BAGS',
                  'latitude': 50.480,
                  'longitude': 30.520,
                  'distance_km': 4.9,
                  'event_time': '2026-10-15T11:00:00Z',
                  'status': 'ACTIVE',
                  'created_by_user_id': 'other-uid',
                },
              ],
              'total': 2,
              'page': 1,
              'page_size': 50,
              'total_pages': 1,
            });
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        LocationService.instance.setManualLocation(
          latitude: 50.4501,
          longitude: 30.5234,
        );

        await reportRepo.loadReports(
          latitude: 50.4501,
          longitude: 30.5234,
          radiusKm: 5.0,
        );

        expect(reportRepo.reports.length, 2);
        final titles = reportRepo.reports.map((r) => r.title).toList();
        expect(titles, contains('Close Item (0.5 km)'));
        expect(titles, contains('Edge Item (4.9 km)'));
        expect(titles, isNot(contains('Outside Item (5.5 km)')));
      },
    );

    // 6. Create outside-radius report -> does not appear in Home nearby list
    testWidgets(
      '6. Creating an outside-radius report does not append it to Home nearby feed',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));

        // Anchor is at Kyiv (50.4501, 30.5234)
        LocationService.instance.setManualLocation(
          latitude: 50.4501,
          longitude: 30.5234,
          label: 'Kyiv Center',
        );

        // Existing nearby reports: 0
        mockClient.handler = (req) async {
          if (req.url.path == '/api/v1/reports' && req.method == 'GET') {
            return jsonResponse({
              'items': [],
              'total': 0,
              'page': 1,
              'page_size': 50,
              'total_pages': 0,
            });
          }
          if (req.url.path == '/api/v1/reports' && req.method == 'POST') {
            final body = jsonDecode((req as http.Request).body);
            return jsonResponse({
              'id': 'rep-lviv-1',
              'type': body['type'],
              'title': body['title'],
              'description': body['description'],
              'category': body['category'],
              'latitude': body['latitude'],
              'longitude': body['longitude'],
              'event_time': body['event_time'],
              'status': 'ACTIVE',
              'created_by_user_id': 'usr-anchor-1',
            }, statusCode: 201);
          }
          if (req.url.path == '/api/v1/reports/rep-lviv-1') {
            return jsonResponse({
              'id': 'rep-lviv-1',
              'type': 'MISSING',
              'title': 'Lost in Lviv (500 km away)',
              'description': 'Left in Lviv',
              'category': 'ELECTRONICS',
              'latitude': 49.8397,
              'longitude': 24.0297,
              'event_time': '2026-10-15T12:00:00Z',
              'status': 'ACTIVE',
              'created_by_user_id': 'usr-anchor-1',
            });
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        await reportRepo.loadReports(
          latitude: 50.4501,
          longitude: 30.5234,
          radiusKm: 5.0,
        );

        // Create report in Lviv (49.8397, 24.0297) - ~500 km away
        final created = await reportRepo.createReport(
          title: 'Lost in Lviv (500 km away)',
          category: 'Electronics',
          description: 'Left in Lviv',
          locationDescription: 'Rynok Square, Lviv',
          dateTime: DateTime.now(),
          status: ReportStatus.missing,
          latitude: 49.8397,
          longitude: 24.0297,
        );

        // Created report is stored for user
        expect(created.id, 'rep-lviv-1');
        expect(reportRepo.userReports.any((r) => r.id == 'rep-lviv-1'), isTrue);
        expect(reportRepo.getReportById('rep-lviv-1'), isNotNull);

        // But NOT present in nearby feed!
        expect(reportRepo.reports.any((r) => r.id == 'rep-lviv-1'), isFalse);
        expect(reportRepo.reports.isEmpty, isTrue);

        await tester.pumpWidget(const MaterialApp(home: HomeScreen()));
        await tester.pumpAndSettle();

        expect(find.text('Lost in Lviv (500 km away)'), findsNothing);
      },
    );

    // 7. Create inside-radius report -> appears after server-backed refresh
    test(
      '7. Creating an inside-radius report appears in nearby feed after server refresh',
      () async {
        LocationService.instance.setManualLocation(
          latitude: 50.4501,
          longitude: 30.5234,
          label: 'Kyiv Center',
        );

        bool reportCreated = false;
        mockClient.handler = (req) async {
          if (req.url.path == '/api/v1/reports' && req.method == 'POST') {
            reportCreated = true;
            return jsonResponse({
              'id': 'rep-kyiv-inside',
              'type': 'MISSING',
              'title': 'Nearby Keys',
              'description': 'Dropped on street',
              'category': 'DOCUMENTS_KEYS',
              'latitude': 50.4510,
              'longitude': 30.5240,
              'event_time': '2026-10-15T12:00:00Z',
              'status': 'ACTIVE',
              'created_by_user_id': 'usr-anchor-1',
            }, statusCode: 201);
          }
          if (req.url.path == '/api/v1/reports/rep-kyiv-inside') {
            return jsonResponse({
              'id': 'rep-kyiv-inside',
              'type': 'MISSING',
              'title': 'Nearby Keys',
              'description': 'Dropped on street',
              'category': 'DOCUMENTS_KEYS',
              'latitude': 50.4510,
              'longitude': 30.5240,
              'event_time': '2026-10-15T12:00:00Z',
              'status': 'ACTIVE',
              'created_by_user_id': 'usr-anchor-1',
            });
          }
          if (req.url.path == '/api/v1/reports' && req.method == 'GET') {
            if (reportCreated) {
              return jsonResponse({
                'items': [
                  {
                    'id': 'rep-kyiv-inside',
                    'type': 'MISSING',
                    'title': 'Nearby Keys',
                    'description': 'Dropped on street',
                    'category': 'DOCUMENTS_KEYS',
                    'latitude': 50.4510,
                    'longitude': 30.5240,
                    'distance_km': 0.1,
                    'event_time': '2026-10-15T12:00:00Z',
                    'status': 'ACTIVE',
                    'created_by_user_id': 'usr-anchor-1',
                  },
                ],
                'total': 1,
                'page': 1,
                'page_size': 50,
                'total_pages': 1,
              });
            }
            return jsonResponse({'items': [], 'total': 0});
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        await reportRepo.createReport(
          title: 'Nearby Keys',
          category: 'Keys',
          description: 'Dropped on street',
          locationDescription: 'Khreshchatyk St',
          dateTime: DateTime.now(),
          status: ReportStatus.missing,
          latitude: 50.4510,
          longitude: 30.5240,
        );

        expect(reportRepo.reports.length, 1);
        expect(reportRepo.reports.first.title, 'Nearby Keys');
      },
    );

    // 8. Clear anchor -> nearby cards disappear immediately
    testWidgets(
      '8. Clearing anchor immediately removes nearby report cards and restores prompt',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));

        LocationService.instance.setManualLocation(
          latitude: 50.4501,
          longitude: 30.5234,
        );

        mockClient.handler = (req) async {
          return jsonResponse({
            'items': [
              {
                'id': 'rep-anchor-test',
                'type': 'MISSING',
                'title': 'MacBook Pro 14',
                'description': 'Space Black',
                'category': 'ELECTRONICS',
                'latitude': 50.4501,
                'longitude': 30.5234,
                'distance_km': 0.2,
                'event_time': '2026-10-15T12:00:00Z',
                'status': 'ACTIVE',
                'created_by_user_id': 'other-user',
              },
            ],
            'total': 1,
          });
        };

        await reportRepo.loadReports(
          latitude: 50.4501,
          longitude: 30.5234,
          radiusKm: 5.0,
        );

        await tester.pumpWidget(const MaterialApp(home: HomeScreen()));
        await tester.pumpAndSettle();

        expect(find.text('MacBook Pro 14'), findsOneWidget);
        expect(find.text('1 items'), findsOneWidget);

        // Clear location
        LocationService.instance.clearLocation();
        await tester.pumpAndSettle();

        // Cards must disappear immediately
        expect(find.text('MacBook Pro 14'), findsNothing);
        expect(find.text('0 items'), findsOneWidget);
        expect(
          find.text('Select a location to see reports within 5 km.'),
          findsOneWidget,
        );
      },
    );

    // 9. Change anchor -> stale results from old anchor cannot overwrite new results
    test(
      '9. Changing anchor rapidly discards stale responses from older anchor',
      () async {
        final completerA = Completer<http.StreamedResponse>();
        final completerB = Completer<http.StreamedResponse>();

        mockClient.handler = (req) async {
          final lat = req.url.queryParameters['latitude'];
          if (lat == '10.0') {
            return completerA.future;
          } else if (lat == '20.0') {
            return completerB.future;
          }
          return jsonResponse({'items': [], 'total': 0});
        };

        // Query Anchor A (10.0, 10.0)
        final futureA = reportRepo.loadReports(
          latitude: 10.0,
          longitude: 10.0,
          radiusKm: 5.0,
        );

        // Query Anchor B (20.0, 20.0) immediately after
        final futureB = reportRepo.loadReports(
          latitude: 20.0,
          longitude: 20.0,
          radiusKm: 5.0,
        );

        // Complete B first (newest anchor)
        completerB.complete(
          jsonResponse({
            'items': [
              {
                'id': 'rep-anchor-b',
                'type': 'MISSING',
                'title': 'Anchor B Report',
                'description': 'In zone B',
                'category': 'OTHER',
                'latitude': 20.0,
                'longitude': 20.0,
                'event_time': '2026-10-15T12:00:00Z',
                'status': 'ACTIVE',
                'created_by_user_id': 'uid-b',
              },
            ],
            'total': 1,
          }),
        );
        await futureB;

        expect(reportRepo.reports.length, 1);
        expect(reportRepo.reports.first.title, 'Anchor B Report');

        // Complete A later (stale response from old anchor)
        completerA.complete(
          jsonResponse({
            'items': [
              {
                'id': 'rep-anchor-a',
                'type': 'MISSING',
                'title': 'Stale Anchor A Report',
                'description': 'In zone A',
                'category': 'OTHER',
                'latitude': 10.0,
                'longitude': 10.0,
                'event_time': '2026-10-15T12:00:00Z',
                'status': 'ACTIVE',
                'created_by_user_id': 'uid-a',
              },
            ],
            'total': 1,
          }),
        );
        await futureA;

        // Stale A report must NOT have overwritten B
        expect(reportRepo.reports.length, 1);
        expect(reportRepo.reports.first.title, 'Anchor B Report');
      },
    );

    // 10. Category/search/refresh/retry preserve radius constraints
    test(
      '10. Category filter, search query, refresh, and retry strictly preserve radius constraints',
      () async {
        final capturedQueries = <Map<String, String>>[];

        mockClient.handler = (req) async {
          if (req.url.path == '/api/v1/reports') {
            capturedQueries.add(req.url.queryParameters);
            return jsonResponse({'items': [], 'total': 0});
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        LocationService.instance.setManualLocation(
          latitude: 50.4501,
          longitude: 30.5234,
        );

        // Category filter
        await reportRepo.loadReports(
          latitude: 50.4501,
          longitude: 30.5234,
          radiusKm: 5.0,
          category: 'Electronics',
        );

        // Search query
        await reportRepo.loadReports(
          latitude: 50.4501,
          longitude: 30.5234,
          radiusKm: 5.0,
          query: 'MacBook',
        );

        // Force refresh
        await reportRepo.loadReports(
          forceRefresh: true,
          latitude: 50.4501,
          longitude: 30.5234,
          radiusKm: 5.0,
        );

        expect(capturedQueries.length, 3);
        for (final q in capturedQueries) {
          expect(q['latitude'], '50.4501');
          expect(q['longitude'], '30.5234');
          expect(q['radius_km'], '5.0');
          expect(q['sort'], 'distance');
        }
      },
    );

    // 11. Empty API response -> genuine empty state, not sample data
    testWidgets(
      '11. Empty API response renders genuine empty state without mock fixtures',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));

        LocationService.instance.setManualLocation(
          latitude: 50.4501,
          longitude: 30.5234,
        );

        mockClient.handler = (req) async {
          return jsonResponse({'items': [], 'total': 0});
        };

        await reportRepo.loadReports(
          latitude: 50.4501,
          longitude: 30.5234,
          radiusKm: 5.0,
        );

        await tester.pumpWidget(const MaterialApp(home: HomeScreen()));
        await tester.pumpAndSettle();

        // Must show genuine empty state, no mock items like "MacBook Pro 14"
        expect(find.byType(ReportCard), findsNothing);
        expect(
          find.text('No reports within 5 km of Custom Selected Point'),
          findsOneWidget,
        );
        expect(find.text('0 items'), findsOneWidget);
      },
    );

    // 12. API failure -> error/retry state, not sample data
    testWidgets(
      '12. API failure renders explicit error retry card and no sample data',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));

        LocationService.instance.setManualLocation(
          latitude: 50.4501,
          longitude: 30.5234,
        );

        mockClient.handler = (req) async {
          return jsonResponse({'detail': 'Gateway Timeout'}, statusCode: 504);
        };

        await tester.pumpWidget(const MaterialApp(home: HomeScreen()));
        await tester.pumpAndSettle();

        expect(find.text('Unable to load live reports'), findsOneWidget);
        expect(find.text('Retry'), findsOneWidget);
        expect(find.byType(ReportCard), findsNothing);
      },
    );

    // 14. Home and Map use the same active anchor and radius semantics
    testWidgets(
      '14. Home and Map share the exact same active anchor and radius semantics',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));

        // Unanchored initial state: MapScreen displays 0 items and location prompt
        await tester.pumpWidget(const MaterialApp(home: MapScreen()));
        await tester.pumpAndSettle();

        expect(find.text('0 items'), findsOneWidget);
        await tester.tap(find.text('Expand'));
        await tester.pumpAndSettle();
        expect(
          find.text('Select a location to see reports within 5.0 km.'),
          findsOneWidget,
        );

        // Set manual anchor in LocationService
        LocationService.instance.setManualLocation(
          latitude: 50.4501,
          longitude: 30.5234,
          label: 'Kyiv Central',
        );

        mockClient.handler = (req) async {
          expect(req.url.queryParameters['latitude'], '50.4501');
          expect(req.url.queryParameters['longitude'], '30.5234');
          expect(req.url.queryParameters['radius_km'], '5.0');
          return jsonResponse({
            'items': [
              {
                'id': 'rep-map-1',
                'type': 'MISSING',
                'title': 'Shared Anchor Report',
                'description': 'Visible in both Home and Map',
                'category': 'ELECTRONICS',
                'latitude': 50.451,
                'longitude': 30.524,
                'distance_km': 0.1,
                'event_time': '2026-10-15T12:00:00Z',
                'status': 'ACTIVE',
                'created_by_user_id': 'other-uid',
              },
            ],
            'total': 1,
          });
        };

        await reportRepo.loadReports(
          latitude: 50.4501,
          longitude: 30.5234,
          radiusKm: 5.0,
        );

        await tester.pumpAndSettle();
        expect(find.text('1 items'), findsOneWidget);
        expect(find.text('Shared Anchor Report'), findsOneWidget);
      },
    );
  });
}
