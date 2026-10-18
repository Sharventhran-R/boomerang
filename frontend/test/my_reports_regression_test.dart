import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:frontend/models/user_model.dart';
import 'package:frontend/services/api_client.dart';
import 'package:frontend/services/auth_service.dart';
import 'package:frontend/services/report_repository.dart';
import 'package:frontend/services/token_storage.dart';
import 'package:frontend/ui/screens/my_reports_screen.dart';
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
  late AuthService authService;
  late ReportRepository reportRepository;

  final userA = UserModel(
    id: 'user-a-uuid',
    email: 'user_a@test.com',
    name: 'User Alpha',
    createdAt: DateTime.now(),
  );

  final userB = UserModel(
    id: 'user-b-uuid',
    email: 'user_b@test.com',
    name: 'User Beta',
    createdAt: DateTime.now(),
  );

  setUp(() {
    mockClient = MockHttpClient();
    apiClient = ApiClient(
      baseUrl: 'http://test-myreports.local',
      client: mockClient,
    );
    authService = AuthService(
      client: apiClient,
      storage: InMemoryTokenStorage(),
    );
    AuthService.setInstanceForTesting(authService);
    reportRepository = ReportRepository.instance;
    reportRepository.configure(client: apiClient, auth: authService);
  });

  group('My Reports Ownership, Discovery Radius & Lifecycle Tests', () {
    test(
      '1 & 2. User creates Missing and Found reports and loads them via loadUserReports',
      () async {
        authService.setSessionForTesting(user: userA, accessToken: 'token-a');

        final userReportsData = <Map<String, dynamic>>[];

        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports' &&
              request.method == 'POST') {
            final body =
                jsonDecode((request as http.Request).body)
                    as Map<String, dynamic>;
            final created = {
              'id': 'rep-${body['type'].toLowerCase()}-123',
              'type': body['type'],
              'title': body['title'],
              'description': body['description'],
              'category': body['category'],
              'latitude': body['latitude'],
              'longitude': body['longitude'],
              'event_time': body['event_time'],
              'reward_amount': body['reward_amount'],
              'status': 'ACTIVE',
              'created_by_user_id': userA.id,
              'created_at': DateTime.now().toIso8601String(),
              'updated_at': DateTime.now().toIso8601String(),
              'images': [],
            };
            userReportsData.add(created);
            return jsonResponse(created, statusCode: 201);
          }
          if (request.url.path == '/api/v1/reports/me' &&
              request.method == 'GET') {
            return jsonResponse({
              'items': userReportsData,
              'total': userReportsData.length,
              'page': 1,
              'page_size': 50,
              'total_pages': 1,
            });
          }
          if (request.url.path.startsWith('/api/v1/reports/') &&
              request.method == 'GET') {
            final id = request.url.pathSegments.last;
            final found = userReportsData.firstWhere(
              (r) => r['id'] == id,
              orElse: () => userReportsData.last,
            );
            return jsonResponse(found);
          }
          if (request.url.path == '/api/v1/reports' &&
              request.method == 'GET') {
            return jsonResponse({
              'items': [],
              'total': 0,
              'page': 1,
              'page_size': 50,
            });
          }
          return jsonResponse({}, statusCode: 404);
        };

        // Create MISSING report
        final missingReport = await reportRepository.createReport(
          title: 'Lost Backpack in Kyiv',
          category: 'Bags',
          description: 'Left near Independence Square',
          locationDescription: 'Kyiv Central',
          dateTime: DateTime.now(),
          status: ReportStatus.missing,
          reward: '\$75',
          latitude: 50.4501,
          longitude: 30.5234,
        );
        expect(missingReport.id, 'rep-missing-123');

        // Create FOUND report
        final foundReport = await reportRepository.createReport(
          title: 'Found Smartwatch',
          category: 'Electronics',
          description: 'Found on bench',
          locationDescription: 'Park bench',
          dateTime: DateTime.now(),
          status: ReportStatus.found,
          reward: null,
          latitude: 50.4520,
          longitude: 30.5250,
        );
        expect(foundReport.id, 'rep-found-123');

        // Verify userReports contains both Missing and Found
        expect(reportRepository.userReports.length, 2);
        final missingItem = reportRepository.userReports.firstWhere(
          (r) => r.status == ReportStatus.missing,
        );
        final foundItem = reportRepository.userReports.firstWhere(
          (r) => r.status == ReportStatus.found,
        );
        expect(missingItem.title, 'Lost Backpack in Kyiv');
        expect(foundItem.title, 'Found Smartwatch');
      },
    );

    test(
      '3 & 6. Reports remain visible in My Reports when incident location is outside discovery radius, but excluded from discovery',
      () async {
        authService.setSessionForTesting(user: userA, accessToken: 'token-a');

        final kyivReport = {
          'id': 'kyiv-rep-outside-radius',
          'type': 'MISSING',
          'title': 'Kyiv Report Far Away',
          'description': 'Out of radius',
          'category': 'ELECTRONICS',
          'latitude': 50.4500,
          'longitude': 30.5200,
          'event_time': '2026-10-18T10:00:00Z',
          'status': 'ACTIVE',
          'created_by_user_id': userA.id,
          'created_at': '2026-10-18T10:00:00Z',
          'updated_at': '2026-10-18T10:00:00Z',
          'images': [],
        };

        mockClient.handler = (request) async {
          // When querying nearby discovery around New York (40.71, -74.00, 5km),
          // backend PostGIS radius filter excludes the Kyiv report
          if (request.url.path == '/api/v1/reports' &&
              request.url.queryParameters.containsKey('latitude')) {
            return jsonResponse({
              'items': [],
              'total': 0,
              'page': 1,
              'page_size': 50,
              'total_pages': 0,
            });
          }

          // When querying /api/v1/reports/me, backend returns all user reports regardless of location
          if (request.url.path == '/api/v1/reports/me') {
            return jsonResponse({
              'items': [kyivReport],
              'total': 1,
              'page': 1,
              'page_size': 50,
              'total_pages': 1,
            });
          }

          return jsonResponse({}, statusCode: 404);
        };

        // 1. Load nearby discovery in New York:
        await reportRepository.loadReports(
          forceRefresh: true,
          latitude: 40.7128,
          longitude: -74.0060,
          radiusKm: 5.0,
        );
        // Discovery feed must exclude the out-of-radius report
        expect(reportRepository.reports, isEmpty);

        // 2. Load user's account reports:
        await reportRepository.loadUserReports(forceRefresh: true);
        // My Reports MUST include the report even though its location is outside the discovery radius!
        expect(reportRepository.userReports.length, 1);
        expect(
          reportRepository.userReports.first.id,
          'kyiv-rep-outside-radius',
        );
        expect(
          reportRepository.userReports.first.title,
          'Kyiv Report Far Away',
        );
      },
    );

    test(
      '4. One user cannot see another users private report records in My Reports',
      () async {
        final userAReport = {
          'id': 'user-a-secret-item',
          'type': 'MISSING',
          'title': 'User A Secret Item',
          'description': 'Private to A',
          'category': 'DOCUMENTS',
          'latitude': 13.0827,
          'longitude': 80.2707,
          'status': 'ACTIVE',
          'created_by_user_id': userA.id,
          'created_at': DateTime.now().toIso8601String(),
          'updated_at': DateTime.now().toIso8601String(),
          'images': [],
        };

        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports/me') {
            final authHeader = request.headers['authorization'];
            if (authHeader == 'Bearer token-a') {
              return jsonResponse({
                'items': [userAReport],
                'total': 1,
                'page': 1,
                'page_size': 50,
                'total_pages': 1,
              });
            } else if (authHeader == 'Bearer token-b') {
              return jsonResponse({
                'items': [],
                'total': 0,
                'page': 1,
                'page_size': 50,
                'total_pages': 0,
              });
            }
            return jsonResponse({
              'detail': 'Not authenticated',
            }, statusCode: 401);
          }
          return jsonResponse({}, statusCode: 404);
        };

        // User A logs in and fetches reports
        authService.setSessionForTesting(user: userA, accessToken: 'token-a');
        await reportRepository.loadUserReports(forceRefresh: true);
        expect(reportRepository.userReports.length, 1);
        expect(reportRepository.userReports.first.id, 'user-a-secret-item');

        // User A logs out
        await authService.logout();
        expect(reportRepository.userReports, isEmpty);

        // User B logs in and fetches reports
        authService.setSessionForTesting(user: userB, accessToken: 'token-b');
        await reportRepository.loadUserReports(forceRefresh: true);
        // User B cannot see User A's reports!
        expect(reportRepository.userReports, isEmpty);
      },
    );

    test(
      '5. Reports remain visible after navigating away and back, and after a fresh authenticated fetch',
      () async {
        authService.setSessionForTesting(user: userA, accessToken: 'token-a');

        int fetchCount = 0;
        final reportItem = {
          'id': 'persisted-report-1',
          'type': 'FOUND',
          'title': 'Found Car Keys',
          'description': 'On the sidewalk',
          'category': 'KEYS',
          'latitude': 50.45,
          'longitude': 30.52,
          'status': 'ACTIVE',
          'created_by_user_id': userA.id,
          'created_at': DateTime.now().toIso8601String(),
          'updated_at': DateTime.now().toIso8601String(),
          'images': [],
        };

        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports/me') {
            fetchCount++;
            return jsonResponse({
              'items': [reportItem],
              'total': 1,
              'page': 1,
              'page_size': 50,
              'total_pages': 1,
            });
          }
          return jsonResponse({}, statusCode: 404);
        };

        // First fetch
        await reportRepository.loadUserReports();
        expect(reportRepository.userReports.length, 1);
        expect(reportRepository.userReports.first.title, 'Found Car Keys');
        expect(fetchCount, 1);

        // Subsequent call without forceRefresh uses cache
        await reportRepository.loadUserReports();
        expect(fetchCount, 1);
        expect(reportRepository.userReports.length, 1);

        // Fresh authenticated fetch with forceRefresh revalidates
        await reportRepository.loadUserReports(forceRefresh: true);
        expect(fetchCount, 2);
        expect(reportRepository.userReports.length, 1);
      },
    );

    testWidgets(
      '7. API errors are handled visibly with a Retry button rather than silently producing an empty list',
      (WidgetTester tester) async {
        authService.setSessionForTesting(user: userA, accessToken: 'token-a');

        bool failApi = true;
        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports/me') {
            if (failApi) {
              return jsonResponse({
                'detail': 'Internal Server Error: Database timeout',
              }, statusCode: 500);
            } else {
              return jsonResponse({
                'items': [
                  {
                    'id': 'recovered-rep-1',
                    'type': 'MISSING',
                    'title': 'Recovered Item Title',
                    'description': 'Description',
                    'category': 'ELECTRONICS',
                    'latitude': 50.45,
                    'longitude': 30.52,
                    'status': 'ACTIVE',
                    'created_by_user_id': userA.id,
                    'created_at': DateTime.now().toIso8601String(),
                    'updated_at': DateTime.now().toIso8601String(),
                    'images': [],
                  },
                ],
                'total': 1,
                'page': 1,
                'page_size': 50,
                'total_pages': 1,
              });
            }
          }
          return jsonResponse({}, statusCode: 404);
        };

        await tester.pumpWidget(const MaterialApp(home: MyReportsScreen()));
        await tester.pumpAndSettle();

        // Must visibly show error state instead of silent empty list
        expect(find.text('Failed to load reports'), findsOneWidget);
        expect(find.text('Retry'), findsOneWidget);
        expect(find.text('No reports matching this filter.'), findsNothing);

        // Tap Retry when API recovers
        failApi = false;
        await tester.tap(find.text('Retry'));
        await tester.pumpAndSettle();

        // Error is cleared and report is rendered!
        expect(find.text('Failed to load reports'), findsNothing);
        expect(find.text('Recovered Item Title'), findsOneWidget);
      },
    );
  });
}
