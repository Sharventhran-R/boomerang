import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:frontend/models/report_model.dart';
import 'package:frontend/models/user_model.dart';
import 'package:frontend/services/api_client.dart';
import 'package:frontend/services/auth_service.dart';
import 'package:frontend/services/location_service.dart';
import 'package:frontend/services/report_repository.dart';
import 'package:frontend/services/token_storage.dart';
import 'package:frontend/ui/screens/create_report_screen.dart';
import 'package:frontend/ui/screens/home_screen.dart';
import 'package:frontend/ui/screens/login_screen.dart';
import 'package:frontend/ui/screens/my_reports_screen.dart';
import 'package:frontend/ui/screens/profile_screen.dart';
import 'package:frontend/ui/screens/registration_screen.dart';
import 'package:frontend/ui/screens/report_details_screen.dart';
import 'package:frontend/ui/widgets/status_label.dart';

/// Configurable Mock HTTP Client for deterministic API testing
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
        headers: {'content-type': 'application/json'},
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
  late MockHttpClient mockClient;
  late TokenStorage tokenStorage;
  late ApiClient apiClient;
  late AuthService authService;
  late ReportRepository reportRepository;

  setUp(() {
    mockClient = MockHttpClient();
    tokenStorage = InMemoryTokenStorage();
    apiClient = ApiClient(baseUrl: 'http://127.0.0.1:8000', client: mockClient);
    authService = AuthService(client: apiClient, storage: tokenStorage);
    AuthService.setInstanceForTesting(authService);

    reportRepository = ReportRepository(
      apiClient: apiClient,
      authService: authService,
    );
    ReportRepository.setInstanceForTesting(reportRepository);
  });

  group('Group 1: Authentication and Session Management', () {
    test(
      'Registration sends POST /api/v1/auth/register and returns UserModel',
      () async {
        http.BaseRequest? capturedRequest;
        mockClient.handler = (request) async {
          capturedRequest = request;
          if (request.url.path == '/api/v1/auth/register' &&
              request.method == 'POST') {
            return jsonResponse({
              'id': 'u-12345',
              'name': 'Test User',
              'email': 'test@example.com',
              'created_at': '2026-10-12T10:00:00Z',
            });
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        final user = await authService.register(
          name: 'Test User',
          email: 'test@example.com',
          password: 'password123',
        );

        expect(user.id, 'u-12345');
        expect(user.name, 'Test User');
        expect(user.email, 'test@example.com');
        expect(capturedRequest?.url.path, '/api/v1/auth/register');
        expect(capturedRequest?.headers['Authorization'], isNull);
      },
    );

    test(
      'Login sends POST /api/v1/auth/login, saves tokens, and fetches profile',
      () async {
        final requestedPaths = <String>[];
        final headersMap = <String, Map<String, String>>{};

        mockClient.handler = (request) async {
          requestedPaths.add(request.url.path);
          headersMap[request.url.path] = Map.from(request.headers);

          if (request.url.path == '/api/v1/auth/login' &&
              request.method == 'POST') {
            return jsonResponse({
              'access_token': 'mock-access-token-111',
              'refresh_token': 'mock-refresh-token-222',
              'token_type': 'bearer',
            });
          } else if (request.url.path == '/api/v1/users/me' &&
              request.method == 'GET') {
            return jsonResponse({
              'id': 'u-12345',
              'name': 'Logged In User',
              'email': 'loggedin@example.com',
              'created_at': '2026-10-12T10:00:00Z',
            });
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        final user = await authService.login(
          email: 'loggedin@example.com',
          password: 'password123',
        );

        expect(user.id, 'u-12345');
        expect(user.name, 'Logged In User');
        expect(authService.isAuthenticated, isTrue);
        expect(authService.currentAccessToken, 'mock-access-token-111');
        expect(await tokenStorage.getAccessToken(), 'mock-access-token-111');
        expect(await tokenStorage.getRefreshToken(), 'mock-refresh-token-222');

        expect(
          requestedPaths,
          containsAllInOrder(['/api/v1/auth/login', '/api/v1/users/me']),
        );
        expect(
          headersMap['/api/v1/users/me']?['Authorization'],
          'Bearer mock-access-token-111',
        );
      },
    );

    test(
      'Login failure throws ApiException and leaves session unauthenticated',
      () async {
        mockClient.handler = (request) async {
          return jsonResponse({
            'detail': 'Invalid email or password',
          }, statusCode: 401);
        };

        expect(
          () => authService.login(email: 'bad@example.com', password: 'bad'),
          throwsA(
            isA<ApiException>().having((e) => e.statusCode, 'statusCode', 401),
          ),
        );

        expect(authService.isAuthenticated, isFalse);
        expect(authService.currentUser, isNull);
        expect(await tokenStorage.getAccessToken(), isNull);
      },
    );

    test(
      'Token refresh rotation saves new tokens and updates accessToken',
      () async {
        await tokenStorage.saveTokens(
          accessToken: 'expired-access-token',
          refreshToken: 'old-refresh-token',
        );

        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/auth/refresh' &&
              request.method == 'POST') {
            return jsonResponse({
              'access_token': 'brand-new-access-token',
              'refresh_token': 'brand-new-refresh-token',
              'token_type': 'bearer',
            });
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        final success = await authService.refreshToken();
        expect(success, isTrue);
        expect(authService.currentAccessToken, 'brand-new-access-token');
        expect(await tokenStorage.getAccessToken(), 'brand-new-access-token');
        expect(await tokenStorage.getRefreshToken(), 'brand-new-refresh-token');
      },
    );

    test(
      'Transparent 401 retry in ApiClient automatically refreshes token',
      () async {
        authService.setSessionForTesting(
          user: UserModel(id: 'u-1', name: 'User', email: 'u@example.com'),
          accessToken: 'initial-expired-token',
          refreshToken: 'initial-refresh-token',
        );

        int protectedCallCount = 0;
        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports' &&
              request.method == 'GET') {
            protectedCallCount++;
            if (protectedCallCount == 1) {
              // First call with initial token fails with 401
              expect(
                request.headers['Authorization'],
                'Bearer initial-expired-token',
              );
              return jsonResponse({'detail': 'Token expired'}, statusCode: 401);
            } else {
              // Second call with refreshed token succeeds
              expect(
                request.headers['Authorization'],
                'Bearer rotated-access-token',
              );
              return jsonResponse({
                'items': [],
                'total': 0,
                'page': 1,
                'page_size': 50,
              });
            }
          } else if (request.url.path == '/api/v1/auth/refresh' &&
              request.method == 'POST') {
            return jsonResponse({
              'access_token': 'rotated-access-token',
              'refresh_token': 'rotated-refresh-token',
              'token_type': 'bearer',
            });
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        final result = await apiClient.get('/api/v1/reports');
        expect(result, isNotNull);
        expect(protectedCallCount, 2);
        expect(authService.currentAccessToken, 'rotated-access-token');
      },
    );

    test(
      'Failed refresh clears session and triggers onSessionExpired',
      () async {
        await tokenStorage.saveTokens(
          accessToken: 'old-access-token',
          refreshToken: 'dead-refresh-token',
        );

        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/auth/refresh') {
            return jsonResponse({
              'detail': 'Refresh token revoked',
            }, statusCode: 401);
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        final refreshed = await authService.refreshToken();
        expect(refreshed, isFalse);
        expect(authService.isAuthenticated, isFalse);
        expect(await tokenStorage.getAccessToken(), isNull);
        expect(await tokenStorage.getRefreshToken(), isNull);
      },
    );

    test(
      'Logout invokes /api/v1/auth/logout and clears local credentials',
      () async {
        await tokenStorage.saveTokens(
          accessToken: 'active-access-token',
          refreshToken: 'active-refresh-token',
        );
        authService.setSessionForTesting(
          user: UserModel(id: 'u-1', name: 'User', email: 'u@example.com'),
          accessToken: 'active-access-token',
          refreshToken: 'active-refresh-token',
        );

        String? logoutRequestBody;
        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/auth/logout' &&
              request.method == 'POST') {
            final bodyBytes = await request.finalize().toBytes();
            logoutRequestBody = utf8.decode(bodyBytes);
            return jsonResponse({'message': 'Successfully logged out'});
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        await authService.logout();

        expect(authService.isAuthenticated, isFalse);
        expect(authService.currentUser, isNull);
        expect(await tokenStorage.getAccessToken(), isNull);
        expect(await tokenStorage.getRefreshToken(), isNull);
        expect(logoutRequestBody, contains('active-refresh-token'));
      },
    );

    test(
      'restoreSession restores profile when valid tokens are stored',
      () async {
        await tokenStorage.saveTokens(
          accessToken: 'stored-access-token',
          refreshToken: 'stored-refresh-token',
        );

        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/users/me') {
            return jsonResponse({
              'id': 'u-restored',
              'name': 'Restored User',
              'email': 'restored@example.com',
              'created_at': '2026-10-12T12:00:00Z',
            });
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        await authService.restoreSession();

        expect(authService.isAuthenticated, isTrue);
        expect(authService.currentUser?.id, 'u-restored');
        expect(authService.currentUser?.name, 'Restored User');
        expect(authService.isInitialized, isTrue);
      },
    );
  });

  group('Group 2: Report Model Serialization & Enums', () {
    test('ReportModel.fromBackendJson parses backend response accurately', () {
      final backendJson = {
        'id': 'e9858599-2d44-4634-8c83-0599cfa58807',
        'type': 'MISSING',
        'title': 'MacBook Pro 16',
        'description': 'Space Black laptop left at coffee bar',
        'category': 'ELECTRONICS',
        'latitude': 50.4501,
        'longitude': 30.5234,
        'event_time': '2026-10-12T14:30:00Z',
        'reward_amount': 250.0,
        'status': 'ACTIVE',
        'created_by_user_id': 'user-uuid-999',
        'created_at': '2026-10-12T14:35:00Z',
        'updated_at': '2026-10-12T14:35:00Z',
        'images': [
          {
            'id': 'img-1',
            'report_id': 'e9858599-2d44-4634-8c83-0599cfa58807',
            'image_url': 'http://127.0.0.1:8000/media/reports/macbook.jpg',
            'created_at': '2026-10-12T14:36:00Z',
          },
        ],
      };

      final report = ReportModel.fromBackendJson(
        backendJson,
        currentUserId: 'user-uuid-999',
      );

      expect(report.id, 'e9858599-2d44-4634-8c83-0599cfa58807');
      expect(report.title, 'MacBook Pro 16');
      expect(report.status, ReportStatus.missing);
      expect(report.backendStatus, 'ACTIVE');
      expect(report.category, 'Electronics');
      expect(report.reward, '\$250');
      expect(report.latitude, 50.4501);
      expect(report.longitude, 30.5234);
      expect(report.createdByUserId, 'user-uuid-999');
      expect(report.isUserReport, isTrue);
      expect(report.images.length, 1);
      expect(
        report.photos.first,
        'http://127.0.0.1:8000/media/reports/macbook.jpg',
      );
    });

    test(
      'toBackendCategory maps all Flutter UI categories to backend enum strings',
      () {
        expect(ReportModel.toBackendCategory('Electronics'), 'ELECTRONICS');
        expect(ReportModel.toBackendCategory('Documents'), 'DOCUMENT');
        expect(ReportModel.toBackendCategory('Keys'), 'KEYS');
        expect(ReportModel.toBackendCategory('Wallet'), 'WALLET');
        expect(ReportModel.toBackendCategory('Bag'), 'BAG');
        expect(ReportModel.toBackendCategory('Pet'), 'PET');
        expect(ReportModel.toBackendCategory('Jewelry'), 'JEWELRY');
        expect(ReportModel.toBackendCategory('Clothing'), 'CLOTHING');
        expect(ReportModel.toBackendCategory('Other'), 'OTHER');
        expect(ReportModel.toBackendCategory('UnknownCategory'), 'OTHER');
      },
    );

    test(
      'isUserReport evaluates to false when createdByUserId does not match current user',
      () {
        final backendJson = {
          'id': 'rep-2',
          'type': 'FOUND',
          'title': 'Keys found',
          'description': 'Found near metro',
          'category': 'DOCUMENTS_KEYS',
          'latitude': 50.45,
          'longitude': 30.52,
          'event_time': '2026-10-12T10:00:00Z',
          'status': 'ACTIVE',
          'created_by_user_id': 'other-user-uuid',
        };

        final report = ReportModel.fromBackendJson(
          backendJson,
          currentUserId: 'my-user-uuid',
        );
        expect(report.isUserReport, isFalse);
      },
    );
  });

  group('Group 3: Report Repository & Listing', () {
    test(
      'loadReports retrieves paginated items and attaches Bearer token',
      () async {
        String? sentAuthHeader;
        Map<String, String>? sentParams;

        authService.setSessionForTesting(
          user: UserModel(id: 'user-1', name: 'User', email: 'u@example.com'),
          accessToken: 'active-auth-token',
        );

        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports') {
            sentAuthHeader = request.headers['Authorization'];
            sentParams = request.url.queryParameters;
            return jsonResponse({
              'items': [
                {
                  'id': 'rep-101',
                  'type': 'MISSING',
                  'title': 'Black Backpack',
                  'description': 'Lost in cafeteria',
                  'category': 'WALLETS_BAGS',
                  'latitude': 50.4501,
                  'longitude': 30.5234,
                  'event_time': '2026-10-12T09:00:00Z',
                  'status': 'ACTIVE',
                  'created_by_user_id': 'user-1',
                },
                {
                  'id': 'rep-102',
                  'type': 'FOUND',
                  'title': 'Silver Watch',
                  'description': 'Found on bench',
                  'category': 'JEWELRY',
                  'latitude': 50.4520,
                  'longitude': 30.5210,
                  'event_time': '2026-10-12T11:00:00Z',
                  'status': 'ACTIVE',
                  'created_by_user_id': 'user-2',
                },
              ],
              'total': 2,
              'page': 1,
              'page_size': 50,
            });
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        await reportRepository.loadReports(forceRefresh: true);

        expect(sentAuthHeader, 'Bearer active-auth-token');
        expect(sentParams?['page'], '1');
        expect(sentParams?['page_size'], '50');
        expect(sentParams?['sort'], 'newest');
        expect(reportRepository.reports.length, 2);
        expect(reportRepository.reports.first.title, 'Black Backpack');
        expect(reportRepository.hasLoaded, isTrue);
        expect(reportRepository.isLoading, isFalse);
      },
    );

    test(
      'loadReports correctly serializes search, category, and status filters',
      () async {
        Map<String, String>? sentParams;
        authService.setSessionForTesting(
          user: UserModel(id: 'user-1', name: 'User', email: 'u@example.com'),
          accessToken: 'token-abc',
        );

        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports') {
            sentParams = request.url.queryParameters;
            return jsonResponse({
              'items': [],
              'total': 0,
              'page': 1,
              'page_size': 50,
            });
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        await reportRepository.loadReports(
          forceRefresh: true,
          category: 'Electronics',
          query: 'ThinkPad',
          statusFilter: 'missing',
        );

        expect(sentParams?['category'], 'ELECTRONICS');
        expect(sentParams?['search'], 'ThinkPad');
        expect(sentParams?['type'], 'MISSING');
      },
    );

    test(
      'userReports filters list strictly by authenticated created_by_user_id',
      () async {
        authService.setSessionForTesting(
          user: UserModel(
            id: 'logged-in-user',
            name: 'Me',
            email: 'me@example.com',
          ),
          accessToken: 'token',
        );

        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports') {
            return jsonResponse({
              'items': [
                {
                  'id': 'my-report',
                  'type': 'MISSING',
                  'title': 'My Report Title',
                  'description': 'Mine',
                  'category': 'ELECTRONICS',
                  'latitude': 50.45,
                  'longitude': 30.52,
                  'event_time': '2026-10-12T10:00:00Z',
                  'status': 'ACTIVE',
                  'created_by_user_id': 'logged-in-user',
                },
                {
                  'id': 'other-report',
                  'type': 'FOUND',
                  'title': 'Someone Else Report',
                  'description': 'Theirs',
                  'category': 'PETS',
                  'latitude': 50.46,
                  'longitude': 30.53,
                  'event_time': '2026-10-12T11:00:00Z',
                  'status': 'ACTIVE',
                  'created_by_user_id': 'other-stranger',
                },
              ],
              'total': 2,
              'page': 1,
              'page_size': 50,
            });
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        await reportRepository.loadReports(forceRefresh: true);

        expect(reportRepository.reports.length, 2);
        expect(reportRepository.userReports.length, 1);
        expect(reportRepository.userReports.first.id, 'my-report');
        expect(reportRepository.userReports.first.title, 'My Report Title');
      },
    );

    test('fetchReportById retrieves single report by UUID', () async {
      mockClient.handler = (request) async {
        if (request.url.path == '/api/v1/reports/rep-custom-id') {
          return jsonResponse({
            'id': 'rep-custom-id',
            'type': 'FOUND',
            'title': 'Car Keys Found',
            'description': 'Toyota keys found at station',
            'category': 'DOCUMENTS_KEYS',
            'latitude': 50.4418,
            'longitude': 30.4883,
            'event_time': '2026-10-12T12:00:00Z',
            'status': 'ACTIVE',
            'created_by_user_id': 'someone-else',
          });
        }
        return jsonResponse({'detail': 'Not found'}, statusCode: 404);
      };

      final report = await reportRepository.fetchReportById('rep-custom-id');
      expect(report, isNotNull);
      expect(report?.id, 'rep-custom-id');
      expect(report?.title, 'Car Keys Found');
      expect(report?.category, 'Documents');
    });

    test('loadReports sets errorMessage on network failure', () async {
      mockClient.handler = (request) async {
        return jsonResponse({
          'detail': 'Internal Server Error',
        }, statusCode: 500);
      };

      await reportRepository.loadReports(forceRefresh: true);
      expect(reportRepository.isLoading, isFalse);
      expect(reportRepository.errorMessage, isNotNull);
      expect(reportRepository.errorMessage, contains('Internal Server Error'));
    });
  });

  group('Group 4: Report Creation & Image Upload Sequencing', () {
    test(
      'createReport for MISSING sends type MISSING, reward, and coordinates',
      () async {
        authService.setSessionForTesting(
          user: UserModel(
            id: 'author-1',
            name: 'Author',
            email: 'author@example.com',
          ),
          accessToken: 'token-creation',
        );

        Map<String, dynamic>? requestPayload;
        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports' &&
              request.method == 'POST') {
            final bodyBytes = await request.finalize().toBytes();
            requestPayload = jsonDecode(utf8.decode(bodyBytes));
            return jsonResponse({
              'id': 'new-uuid-001',
              'type': requestPayload!['type'],
              'title': requestPayload!['title'],
              'description': requestPayload!['description'],
              'category': requestPayload!['category'],
              'latitude': requestPayload!['latitude'],
              'longitude': requestPayload!['longitude'],
              'event_time': requestPayload!['event_time'],
              'reward_amount': requestPayload!['reward_amount'],
              'status': 'ACTIVE',
              'created_by_user_id': 'author-1',
            }, statusCode: 201);
          } else if (request.url.path == '/api/v1/reports/new-uuid-001') {
            return jsonResponse({
              'id': 'new-uuid-001',
              'type': 'MISSING',
              'title': 'Lost Drone',
              'description': 'DJI Mavic 3 lost over park',
              'category': 'ELECTRONICS',
              'latitude': 50.4501,
              'longitude': 30.5234,
              'event_time': '2026-10-12T15:00:00Z',
              'reward_amount': 150.0,
              'status': 'ACTIVE',
              'created_by_user_id': 'author-1',
            });
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        final created = await reportRepository.createReport(
          title: 'Lost Drone',
          category: 'Electronics',
          description: 'DJI Mavic 3 lost over park',
          locationDescription: 'Downtown Kyiv',
          dateTime: DateTime.parse('2026-10-12T15:00:00Z'),
          status: ReportStatus.missing,
          reward: '150',
          latitude: 50.4501,
          longitude: 30.5234,
        );

        expect(created.id, 'new-uuid-001');
        expect(created.title, 'Lost Drone');
        expect(requestPayload?['type'], 'MISSING');
        expect(requestPayload?['category'], 'ELECTRONICS');
        expect(requestPayload?['latitude'], 50.4501);
        expect(requestPayload?['longitude'], 30.5234);
        expect(requestPayload?['reward_amount'], 150.0);
      },
    );

    test(
      'createReport for FOUND omits reward_amount even if reward was provided',
      () async {
        authService.setSessionForTesting(
          user: UserModel(
            id: 'author-2',
            name: 'Author',
            email: 'author2@example.com',
          ),
          accessToken: 'token-creation-2',
        );

        Map<String, dynamic>? requestPayload;
        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports' &&
              request.method == 'POST') {
            final bodyBytes = await request.finalize().toBytes();
            requestPayload = jsonDecode(utf8.decode(bodyBytes));
            return jsonResponse({
              'id': 'found-uuid-002',
              'type': 'FOUND',
              'title': 'Found Kitten',
              'description': 'Small ginger kitten',
              'category': 'PETS',
              'latitude': 50.4633,
              'longitude': 30.5186,
              'event_time': '2026-10-12T16:00:00Z',
              'reward_amount': null,
              'status': 'ACTIVE',
              'created_by_user_id': 'author-2',
            }, statusCode: 201);
          } else if (request.url.path == '/api/v1/reports/found-uuid-002') {
            return jsonResponse({
              'id': 'found-uuid-002',
              'type': 'FOUND',
              'title': 'Found Kitten',
              'description': 'Small ginger kitten',
              'category': 'PETS',
              'latitude': 50.4633,
              'longitude': 30.5186,
              'event_time': '2026-10-12T16:00:00Z',
              'reward_amount': null,
              'status': 'ACTIVE',
              'created_by_user_id': 'author-2',
            });
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        await reportRepository.createReport(
          title: 'Found Kitten',
          category: 'Pet',
          description: 'Small ginger kitten',
          locationDescription: 'Podil',
          dateTime: DateTime.parse('2026-10-12T16:00:00Z'),
          status: ReportStatus.found,
          reward: '500', // Should be ignored because status is FOUND
          latitude: 50.4633,
          longitude: 30.5186,
        );

        expect(requestPayload?['type'], 'FOUND');
        expect(requestPayload?['reward_amount'], isNull);
      },
    );

    test('createReport handles backend validation error (422)', () async {
      authService.setSessionForTesting(
        user: UserModel(
          id: 'author-3',
          name: 'Author',
          email: 'author3@example.com',
        ),
        accessToken: 'token-creation-3',
      );

      mockClient.handler = (request) async {
        if (request.url.path == '/api/v1/reports') {
          return jsonResponse({
            'detail': [
              {
                'loc': ['body', 'latitude'],
                'msg': 'Input should be greater than or equal to -90',
                'type': 'greater_than_equal',
              },
            ],
          }, statusCode: 422);
        }
        return jsonResponse({'detail': 'Not found'}, statusCode: 404);
      };

      expect(
        () => reportRepository.createReport(
          title: 'Invalid coordinates',
          category: 'Other',
          description: 'Testing 422',
          locationDescription: 'Anywhere',
          dateTime: DateTime.now(),
          status: ReportStatus.missing,
          latitude: -100.0,
          longitude: 30.0,
        ),
        throwsA(
          isA<ApiException>().having((e) => e.statusCode, 'statusCode', 422),
        ),
      );
    });

    test(
      'Image upload is sequenced after report creation and handles failures',
      () async {
        authService.setSessionForTesting(
          user: UserModel(
            id: 'author-4',
            name: 'Author',
            email: 'author4@example.com',
          ),
          accessToken: 'token-creation-4',
        );

        final executedCalls = <String>[];
        mockClient.handler = (request) async {
          executedCalls.add('${request.method} ${request.url.path}');

          if (request.url.path == '/api/v1/reports' &&
              request.method == 'POST') {
            return jsonResponse({
              'id': 'img-test-report-01',
              'type': 'MISSING',
              'title': 'Camera with Photos',
              'description': 'Camera',
              'category': 'ELECTRONICS',
              'latitude': 50.45,
              'longitude': 30.52,
              'event_time': '2026-10-12T10:00:00Z',
              'status': 'ACTIVE',
              'created_by_user_id': 'author-4',
            }, statusCode: 201);
          } else if (request.url.path ==
              '/api/v1/reports/img-test-report-01/images') {
            // Verify it's a multipart request with Bearer token
            expect(request.headers['Authorization'], 'Bearer token-creation-4');
            return jsonResponse({
              'id': 'img-uuid-1',
              'report_id': 'img-test-report-01',
              'image_url': 'http://127.0.0.1:8000/media/reports/img-uuid-1.jpg',
              'created_at': '2026-10-12T10:01:00Z',
            }, statusCode: 201);
          } else if (request.url.path == '/api/v1/reports/img-test-report-01' &&
              request.method == 'GET') {
            return jsonResponse({
              'id': 'img-test-report-01',
              'type': 'MISSING',
              'title': 'Camera with Photos',
              'description': 'Camera',
              'category': 'ELECTRONICS',
              'latitude': 50.45,
              'longitude': 30.52,
              'event_time': '2026-10-12T10:00:00Z',
              'status': 'ACTIVE',
              'created_by_user_id': 'author-4',
              'images': [
                {
                  'id': 'img-uuid-1',
                  'report_id': 'img-test-report-01',
                  'image_url':
                      'http://127.0.0.1:8000/media/reports/img-uuid-1.jpg',
                  'created_at': '2026-10-12T10:01:00Z',
                },
              ],
            });
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        final report = await reportRepository.createReport(
          title: 'Camera with Photos',
          category: 'Electronics',
          description: 'Camera',
          locationDescription: 'Downtown',
          dateTime: DateTime.now(),
          status: ReportStatus.missing,
          photoBytesList: [
            [0xFF, 0xD8, 0xFF, 0xE0], // Mock JPEG bytes
          ],
        );

        expect(report.id, 'img-test-report-01');
        expect(
          executedCalls,
          containsAllInOrder([
            'POST /api/v1/reports',
            'POST /api/v1/reports/img-test-report-01/images',
            'GET /api/v1/reports/img-test-report-01',
          ]),
        );
      },
    );
  });

  group('Group 5: UI & Widget Integration Tests', () {
    testWidgets('LoginScreen updates state on successful login', (
      WidgetTester tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));

      mockClient.handler = (request) async {
        if (request.url.path == '/api/v1/auth/login') {
          return jsonResponse({
            'access_token': 'ui-test-access-token',
            'refresh_token': 'ui-test-refresh-token',
            'token_type': 'bearer',
          });
        } else if (request.url.path == '/api/v1/users/me') {
          return jsonResponse({
            'id': 'ui-user-1',
            'name': 'UI Tester',
            'email': 'tester@example.com',
            'created_at': '2026-10-12T00:00:00Z',
          });
        }
        return jsonResponse({'detail': 'Not found'}, statusCode: 404);
      };

      await tester.pumpWidget(const MaterialApp(home: LoginScreen()));
      await tester.pumpAndSettle();

      expect(find.text('Welcome back'), findsOneWidget);

      await tester.enterText(
        find.byKey(const Key('login_email_field')),
        'tester@example.com',
      );
      await tester.enterText(
        find.byKey(const Key('login_password_field')),
        'correctpassword',
      );
      await tester.pumpAndSettle();

      await tester.tap(find.widgetWithText(ElevatedButton, 'Log In'));
      await tester.pump();
      await tester.pumpAndSettle();

      expect(authService.isAuthenticated, isTrue);
      expect(authService.currentUser?.email, 'tester@example.com');
    });

    testWidgets('ProfileScreen displays real user data and allows logout', (
      WidgetTester tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));

      authService.setSessionForTesting(
        user: UserModel(
          id: 'prof-user',
          name: 'Alex Rover',
          email: 'alex.rover@example.com',
        ),
        accessToken: 'prof-token',
        refreshToken: 'prof-refresh',
      );

      mockClient.handler = (request) async {
        if (request.url.path == '/api/v1/auth/logout') {
          return jsonResponse({'message': 'Logged out'});
        }
        return jsonResponse({'detail': 'Not found'}, statusCode: 404);
      };

      await tester.pumpWidget(const MaterialApp(home: ProfileScreen()));
      await tester.pumpAndSettle();

      expect(find.text('Alex Rover'), findsOneWidget);
      expect(find.textContaining('alex.rover@example.com'), findsOneWidget);
      expect(find.text('AR'), findsOneWidget); // Initials
      expect(find.text('VERIFIED MEMBER'), findsOneWidget);

      // Scroll to ensure Log Out button is visible
      await tester.ensureVisible(find.text('Terminate & Log Out'));
      await tester.tap(find.text('Terminate & Log Out'));
      await tester.pumpAndSettle();

      await tester.tap(find.widgetWithText(ElevatedButton, 'Log Out'));
      await tester.pumpAndSettle();

      expect(authService.isAuthenticated, isFalse);
    });

    testWidgets('HomeScreen displays API reports and retry button on error', (
      WidgetTester tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));

      bool shouldFail = true;
      mockClient.handler = (request) async {
        if (request.url.path == '/api/v1/reports') {
          if (shouldFail) {
            return jsonResponse({
              'detail': 'Server temporarily unavailable',
            }, statusCode: 503);
          } else {
            return jsonResponse({
              'items': [
                {
                  'id': 'api-rep-1',
                  'type': 'MISSING',
                  'title': 'AirPods Pro Case',
                  'description': 'White case with sticker',
                  'category': 'ELECTRONICS',
                  'latitude': 50.4501,
                  'longitude': 30.5234,
                  'event_time': '2026-10-12T10:00:00Z',
                  'status': 'ACTIVE',
                  'created_by_user_id': 'other-uid',
                },
              ],
              'total': 1,
              'page': 1,
              'page_size': 50,
            });
          }
        }
        return jsonResponse({'detail': 'Not found'}, statusCode: 404);
      };

      LocationService.instance.setManualLocation(
        latitude: 50.4501,
        longitude: 30.5234,
      );

      await tester.pumpWidget(const MaterialApp(home: HomeScreen()));
      await tester.pumpAndSettle();

      // Should show error card
      expect(find.text('Unable to load live reports'), findsOneWidget);
      expect(find.text('Retry'), findsOneWidget);

      // Now set shouldFail to false and tap retry
      shouldFail = false;
      await tester.tap(find.text('Retry'));
      await tester.pump();
      await tester.pumpAndSettle();

      expect(find.text('AirPods Pro Case'), findsOneWidget);
      expect(find.text('Unable to load live reports'), findsNothing);

      LocationService.instance.clearLocation();
    });

    testWidgets('ReportDetailsScreen displays full details by report ID', (
      WidgetTester tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));

      mockClient.handler = (request) async {
        if (request.url.path == '/api/v1/reports/target-report-id') {
          return jsonResponse({
            'id': 'target-report-id',
            'type': 'MISSING',
            'title': 'Vintage Leather Jacket',
            'description': 'Brown leather jacket left on coat rack',
            'category': 'CLOTHING',
            'latitude': 50.4501,
            'longitude': 30.5234,
            'event_time': '2026-10-12T18:00:00Z',
            'reward_amount': 80.0,
            'status': 'ACTIVE',
            'created_by_user_id': 'owner-id',
          });
        }
        return jsonResponse({'detail': 'Not found'}, statusCode: 404);
      };

      await tester.pumpWidget(
        const MaterialApp(
          home: ReportDetailsScreen(reportId: 'target-report-id'),
        ),
      );
      await tester.pump();
      await tester.pumpAndSettle();

      expect(find.text('Vintage Leather Jacket'), findsOneWidget);
      expect(
        find.text('Brown leather jacket left on coat rack'),
        findsOneWidget,
      );
      expect(find.textContaining('80'), findsOneWidget);
      expect(find.textContaining('50.4501'), findsOneWidget);
    });

    testWidgets(
      'MyReportsScreen displays unauthenticated banner when user is logged out',
      (WidgetTester tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));

        await tester.pumpWidget(const MaterialApp(home: MyReportsScreen()));
        await tester.pumpAndSettle();

        expect(find.text('Authentication Required'), findsOneWidget);
        expect(find.text('Log In'), findsOneWidget);
      },
    );

    testWidgets('RegistrationScreen calls authService.register and succeeds', (
      WidgetTester tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));

      mockClient.handler = (request) async {
        if (request.url.path == '/api/v1/auth/register') {
          return jsonResponse({
            'id': 'reg-user-1',
            'name': 'New User',
            'email': 'newuser@example.com',
            'created_at': '2026-10-12T00:00:00Z',
          });
        } else if (request.url.path == '/api/v1/auth/login') {
          return jsonResponse({
            'access_token': 'new-user-token',
            'refresh_token': 'new-user-refresh',
            'token_type': 'bearer',
          });
        } else if (request.url.path == '/api/v1/users/me') {
          return jsonResponse({
            'id': 'reg-user-1',
            'name': 'New User',
            'email': 'newuser@example.com',
            'created_at': '2026-10-12T00:00:00Z',
          });
        }
        return jsonResponse({'detail': 'Not found'}, statusCode: 404);
      };

      await tester.pumpWidget(const MaterialApp(home: RegistrationScreen()));
      await tester.pumpAndSettle();

      expect(find.text('Create your account'), findsOneWidget);

      await tester.enterText(
        find.byKey(const Key('reg_name_field')),
        'New User',
      );
      await tester.enterText(
        find.byKey(const Key('reg_email_field')),
        'newuser@example.com',
      );
      await tester.enterText(
        find.byKey(const Key('reg_password_field')),
        'password123',
      );
      await tester.pumpAndSettle();

      await tester.tap(find.widgetWithText(ElevatedButton, 'Create Account'));
      await tester.pump();
      await tester.pumpAndSettle();

      expect(authService.isAuthenticated, isTrue);
      expect(authService.currentUser?.name, 'New User');
    });

    testWidgets('CreateReportScreen validates manual coordinates range', (
      WidgetTester tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));

      await tester.pumpWidget(
        const MaterialApp(
          home: CreateReportScreen(initialStatus: ReportStatus.missing),
        ),
      );
      await tester.pumpAndSettle();

      final latFinder = find.byKey(const Key('create_report_latitude_field'));
      expect(latFinder, findsOneWidget);

      await tester.enterText(latFinder, '120.0');
      await tester.pumpAndSettle();

      // Enter title to pass title validation
      await tester.enterText(
        find.widgetWithText(
          TextFormField,
          'e.g., MacBook Pro 14 (Space Black)',
        ),
        'Test Item',
      );
      await tester.pumpAndSettle();

      // Submit
      await tester.ensureVisible(find.text('Publish Missing Report'));
      await tester.tap(find.text('Publish Missing Report'));
      await tester.pumpAndSettle();

      // Validation error for latitude must appear
      expect(find.text('-90 to 90'), findsOneWidget);
    });
  });
}
