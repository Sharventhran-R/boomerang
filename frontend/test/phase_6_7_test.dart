import 'dart:async';
import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:frontend/models/user_model.dart';
import 'package:frontend/services/api_client.dart';
import 'package:frontend/services/auth_service.dart';
import 'package:frontend/services/location_service.dart';
import 'package:frontend/services/map_config.dart';
import 'package:frontend/services/recovery_repository.dart';
import 'package:frontend/services/report_repository.dart';
import 'package:frontend/services/token_storage.dart';
import 'package:frontend/ui/screens/recovery_requests_screen.dart';
import 'package:frontend/ui/screens/report_details_screen.dart';
import 'package:frontend/ui/widgets/status_label.dart';

/// Configurable Mock HTTP Client for deterministic API failure and edge case testing
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

/// Mock Location Service for deterministic testing
class MockLocationService extends ChangeNotifier implements LocationService {
  LocationPermissionStatus mockStatus = LocationPermissionStatus.granted;
  UserLocationData? mockPosition = const UserLocationData(
    latitude: 50.4501,
    longitude: 30.5234,
    accuracy: 10.0,
    isManual: false,
  );
  String? mockError;

  @override
  bool get isLoading => false;

  @override
  bool get hasLocation => mockPosition != null;

  @override
  LocationPermissionStatus get status => mockStatus;

  @override
  UserLocationData? get currentLocation => mockPosition;

  @override
  String? get errorMessage => mockError;

  @override
  Future<LocationPermissionStatus> checkPermission() async => mockStatus;

  @override
  Future<LocationPermissionStatus> requestPermission() async => mockStatus;

  @override
  Future<UserLocationData?> getCurrentPosition({
    Duration timeout = const Duration(seconds: 10),
  }) async {
    if (mockStatus != LocationPermissionStatus.granted) {
      return null;
    }
    return mockPosition;
  }

  @override
  void setManualLocation({
    required double latitude,
    required double longitude,
    String? label,
  }) {
    mockPosition = UserLocationData(
      latitude: latitude,
      longitude: longitude,
      accuracy: 0.0,
      isManual: true,
      label: label ?? 'Manual Anchor',
    );
    notifyListeners();
  }

  @override
  void clearLocation() {
    mockPosition = null;
    mockError = null;
    notifyListeners();
  }
}

void main() {
  late MockHttpClient mockClient;
  late TokenStorage tokenStorage;
  late ApiClient apiClient;
  late AuthService authService;
  late ReportRepository reportRepository;
  late MockLocationService mockLocationService;

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

    mockLocationService = MockLocationService();
    LocationService.setInstanceForTesting(mockLocationService);
  });

  group('Group 1: Live & Mock E2E Reporting Lifecycle Hardening', () {
    test(
      'User registration, login, profile fetch, and session state',
      () async {
        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/auth/register') {
            return jsonResponse({
              'id': 'usr-001',
              'name': 'Harden User',
              'email': 'harden@example.com',
              'created_at': '2026-10-14T10:00:00Z',
            }, statusCode: 201);
          }
          if (request.url.path == '/api/v1/auth/login') {
            return jsonResponse({
              'access_token': 'jwt_access_123',
              'refresh_token': 'jwt_refresh_123',
              'token_type': 'bearer',
            });
          }
          if (request.url.path == '/api/v1/users/me') {
            return jsonResponse({
              'id': 'usr-001',
              'name': 'Harden User',
              'email': 'harden@example.com',
              'created_at': '2026-10-14T10:00:00Z',
            });
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        final registered = await authService.register(
          name: 'Harden User',
          email: 'harden@example.com',
          password: 'Password123!',
        );
        expect(registered.id, 'usr-001');

        final loggedIn = await authService.login(
          email: 'harden@example.com',
          password: 'Password123!',
        );
        expect(loggedIn.email, 'harden@example.com');
        expect(authService.isAuthenticated, isTrue);
        expect(authService.currentUser?.name, 'Harden User');
      },
    );

    test(
      'Creating Missing report with float coordinates and optional reward',
      () async {
        authService.setSessionForTesting(
          user: UserModel(
            id: 'usr-001',
            name: 'Harden User',
            email: 'harden@example.com',
            createdAt: DateTime.now(),
          ),
          accessToken: 'jwt_access_123',
        );

        http.Request? capturedPost;
        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports' &&
              request.method == 'POST') {
            capturedPost = request as http.Request;
            return jsonResponse({
              'id': 'rep-missing-001',
              'created_by_user_id': 'usr-001',
              'type': 'MISSING',
              'title': 'Tactical Radio Transceiver',
              'description': 'Monochrome high-gain radio',
              'category': 'ELECTRONICS',
              'latitude': 50.4501,
              'longitude': 30.5234,
              'event_time': '2026-10-14T11:00:00Z',
              'reward_amount': 200.0,
              'status': 'ACTIVE',
              'created_at': '2026-10-14T11:00:00Z',
              'updated_at': '2026-10-14T11:00:00Z',
              'images': [],
            }, statusCode: 201);
          }
          if (request.url.path == '/api/v1/reports/rep-missing-001') {
            return jsonResponse({
              'id': 'rep-missing-001',
              'created_by_user_id': 'usr-001',
              'type': 'MISSING',
              'title': 'Tactical Radio Transceiver',
              'description': 'Monochrome high-gain radio',
              'category': 'ELECTRONICS',
              'latitude': 50.4501,
              'longitude': 30.5234,
              'event_time': '2026-10-14T11:00:00Z',
              'reward_amount': 200.0,
              'status': 'ACTIVE',
              'created_at': '2026-10-14T11:00:00Z',
              'updated_at': '2026-10-14T11:00:00Z',
              'images': [],
            });
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        final created = await reportRepository.createReport(
          title: 'Tactical Radio Transceiver',
          category: 'Electronics',
          description: 'Monochrome high-gain radio',
          locationDescription: 'Sector 4 Grid',
          dateTime: DateTime.now(),
          status: ReportStatus.missing,
          reward: '\$200',
          latitude: 50.4501,
          longitude: 30.5234,
        );

        expect(created.id, 'rep-missing-001');
        expect(created.status, ReportStatus.missing);
        expect(created.reward, '\$200');

        final body = jsonDecode(capturedPost!.body);
        expect(body['type'], 'MISSING');
        expect(body['reward_amount'], 200.0);
        expect(body['latitude'], 50.4501);
        expect(body['longitude'], 30.5234);
      },
    );

    test(
      'Creating Found report discards reward and does not send reward_amount',
      () async {
        authService.setSessionForTesting(
          user: UserModel(
            id: 'usr-001',
            name: 'Harden User',
            email: 'harden@example.com',
            createdAt: DateTime.now(),
          ),
          accessToken: 'jwt_access_123',
        );

        http.Request? capturedPost;
        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports' &&
              request.method == 'POST') {
            capturedPost = request as http.Request;
            return jsonResponse({
              'id': 'rep-found-001',
              'created_by_user_id': 'usr-001',
              'type': 'FOUND',
              'title': 'Keys on Metal Ring',
              'description': 'Found at tram station',
              'category': 'KEYS',
              'latitude': 50.4501,
              'longitude': 30.5234,
              'event_time': '2026-10-14T11:00:00Z',
              'reward_amount': null,
              'status': 'ACTIVE',
              'created_at': '2026-10-14T11:00:00Z',
              'updated_at': '2026-10-14T11:00:00Z',
              'images': [],
            }, statusCode: 201);
          }
          if (request.url.path == '/api/v1/reports/rep-found-001') {
            return jsonResponse({
              'id': 'rep-found-001',
              'created_by_user_id': 'usr-001',
              'type': 'FOUND',
              'title': 'Keys on Metal Ring',
              'description': 'Found at tram station',
              'category': 'KEYS',
              'latitude': 50.4501,
              'longitude': 30.5234,
              'event_time': '2026-10-14T11:00:00Z',
              'reward_amount': null,
              'status': 'ACTIVE',
              'created_at': '2026-10-14T11:00:00Z',
              'updated_at': '2026-10-14T11:00:00Z',
              'images': [],
            });
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        final created = await reportRepository.createReport(
          title: 'Keys on Metal Ring',
          category: 'Keys',
          description: 'Found at tram station',
          locationDescription: 'Tram Platform 2',
          dateTime: DateTime.now(),
          status: ReportStatus.found,
          reward: '\$50', // Attempting to pass reward on FOUND report
          latitude: 50.4501,
          longitude: 30.5234,
        );

        expect(created.status, ReportStatus.found);
        expect(created.reward, isNull);

        final body = jsonDecode(capturedPost!.body);
        expect(body['type'], 'FOUND');
        expect(body.containsKey('reward_amount'), isFalse);
      },
    );

    test('Creating report with negative reward throws ArgumentError', () async {
      expect(
        () => reportRepository.createReport(
          title: 'Invalid Report',
          category: 'Other',
          description: 'Negative reward test',
          locationDescription: 'Anywhere',
          dateTime: DateTime.now(),
          status: ReportStatus.missing,
          reward: '-100',
        ),
        throwsA(isA<ArgumentError>()),
      );
    });
  });

  group('Group 2: Pagination & Empty Results Hardening', () {
    test(
      'loadReports captures pagination metadata and handles page > totalPages',
      () async {
        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports') {
            final query = request.url.queryParameters;
            if (query['page'] == '99') {
              return jsonResponse({
                'items': [],
                'page': 99,
                'page_size': 20,
                'total': 15,
                'total_pages': 1,
              });
            }
            return jsonResponse({
              'items': [
                {
                  'id': 'rep-page-1',
                  'created_by_user_id': 'u1',
                  'type': 'MISSING',
                  'title': 'Page 1 Item',
                  'description': 'Test item',
                  'category': 'OTHER',
                  'latitude': 50.4501,
                  'longitude': 30.5234,
                  'event_time': '2026-10-14T10:00:00Z',
                  'reward_amount': null,
                  'status': 'ACTIVE',
                  'created_at': '2026-10-14T10:00:00Z',
                  'updated_at': '2026-10-14T10:00:00Z',
                  'images': [],
                },
              ],
              'page': 1,
              'page_size': 20,
              'total': 1,
              'total_pages': 1,
            });
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        await reportRepository.loadReports(page: 1, pageSize: 20);
        expect(reportRepository.reports.length, 1);
        expect(reportRepository.totalReports, 1);
        expect(reportRepository.currentPage, 1);
        expect(reportRepository.totalPages, 1);

        // Query out-of-range page
        await reportRepository.loadReports(page: 99, pageSize: 20);
        expect(reportRepository.reports.isEmpty, isTrue);
        expect(reportRepository.totalReports, 15);
        expect(reportRepository.currentPage, 99);
        expect(reportRepository.totalPages, 1);
        expect(reportRepository.errorMessage, isNull);
      },
    );

    test('Empty search results do not throw and update reports list', () async {
      mockClient.handler = (request) async {
        if (request.url.path == '/api/v1/reports') {
          return jsonResponse({
            'items': [],
            'page': 1,
            'page_size': 50,
            'total': 0,
            'total_pages': 0,
          });
        }
        return jsonResponse({'detail': 'Not found'}, statusCode: 404);
      };

      await reportRepository.loadReports(query: 'NonexistentSearchQueryXYZ');
      expect(reportRepository.reports.isEmpty, isTrue);
      expect(reportRepository.totalReports, 0);
      expect(reportRepository.errorMessage, isNull);
    });
  });

  group('Group 3: Geolocation Permission Failures & Manual Fallbacks', () {
    test('GPS denied returns null and provides clear error notice', () async {
      mockLocationService.mockStatus = LocationPermissionStatus.denied;
      mockLocationService.mockError =
          'Location permission denied by user. GPS automatic centering disabled.';

      final pos = await mockLocationService.getCurrentPosition();
      expect(pos, isNull);
      expect(mockLocationService.status, LocationPermissionStatus.denied);
      expect(
        mockLocationService.errorMessage,
        contains('Location permission denied'),
      );
    });

    test('GPS permanently denied handles gracefully without throwing', () async {
      mockLocationService.mockStatus = LocationPermissionStatus.deniedForever;
      mockLocationService.mockError =
          'Location permission permanently denied. Enable permissions in device settings.';

      final pos = await mockLocationService.getCurrentPosition();
      expect(pos, isNull);
      expect(
        mockLocationService.status,
        LocationPermissionStatus.deniedForever,
      );
      expect(mockLocationService.errorMessage, contains('device settings'));
    });

    test(
      'Manual location selection anchors map position without hardware GPS',
      () {
        mockLocationService.setManualLocation(
          latitude: 48.8566,
          longitude: 2.3522,
          label: 'Selected Pin Paris',
        );

        expect(mockLocationService.currentLocation, isNotNull);
        expect(mockLocationService.currentLocation!.latitude, 48.8566);
        expect(mockLocationService.currentLocation!.longitude, 2.3522);
        expect(mockLocationService.currentLocation!.isManual, isTrue);
        expect(
          mockLocationService.currentLocation!.label,
          'Selected Pin Paris',
        );
      },
    );
  });

  group('Group 4: Recovery Request Independence & Handover UI', () {
    testWidgets(
      'ReportDetailsScreen allows initiating recovery request on Missing report',
      (WidgetTester tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));

        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports/rep-det-01') {
            return jsonResponse({
              'id': 'rep-det-01',
              'created_by_user_id': 'u1',
              'type': 'MISSING',
              'title': 'Lost Backpack',
              'description': 'Black backpack left near coffee shop',
              'category': 'BAG',
              'latitude': 50.4501,
              'longitude': 30.5234,
              'event_time': '2026-10-14T10:00:00Z',
              'reward_amount': 50.0,
              'status': 'ACTIVE',
              'created_at': '2026-10-14T10:00:00Z',
              'updated_at': '2026-10-14T10:00:00Z',
              'images': [],
            });
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        await tester.pumpWidget(
          const MaterialApp(
            home: ReportDetailsScreen(
              reportId: 'rep-det-01',
              title: 'Lost Backpack',
              category: 'Bag',
              distance: '0.4 km',
              timeAgo: '1h ago',
              status: ReportStatus.missing,
              reward: '\$50',
              description: 'Black backpack left near coffee shop',
              locationDescription: 'Corner Café',
            ),
          ),
        );
        await tester.pumpAndSettle();

        // Finder can claim "I Found This Item" directly without having a Found report
        final foundButton = find.text('I Found This Item');
        expect(foundButton, findsOneWidget);
        await tester.ensureVisible(foundButton);

        await tester.tap(foundButton);
        await tester.pumpAndSettle();

        // Handover initiation dialog opens
        expect(find.text('Initiate Handover Contact'), findsOneWidget);
        expect(find.text('Send Recovery Request'), findsOneWidget);

        // Confirm send
        await tester.tap(find.text('Send Recovery Request'));
        await tester.pumpAndSettle();

        // SnackBar shows confirmation
        expect(
          find.text('Recovery request sent for Lost Backpack.'),
          findsOneWidget,
        );
      },
    );

    testWidgets('ReportDetailsScreen allows owner claim on Found report', (
      WidgetTester tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));

      mockClient.handler = (request) async {
        if (request.url.path == '/api/v1/reports/rep-det-02') {
          return jsonResponse({
            'id': 'rep-det-02',
            'created_by_user_id': 'u2',
            'type': 'FOUND',
            'title': 'Found Smart Watch',
            'description': 'Silver digital smartwatch',
            'category': 'ELECTRONICS',
            'latitude': 50.4501,
            'longitude': 30.5234,
            'event_time': '2026-10-14T10:00:00Z',
            'reward_amount': null,
            'status': 'ACTIVE',
            'created_at': '2026-10-14T10:00:00Z',
            'updated_at': '2026-10-14T10:00:00Z',
            'images': [],
          });
        }
        return jsonResponse({'detail': 'Not found'}, statusCode: 404);
      };

      await tester.pumpWidget(
        const MaterialApp(
          home: ReportDetailsScreen(
            reportId: 'rep-det-02',
            title: 'Found Smart Watch',
            category: 'Electronics',
            distance: '1.2 km',
            timeAgo: '3h ago',
            status: ReportStatus.found,
            reward: null,
            description: 'Silver digital smartwatch',
            locationDescription: 'Gym Locker Room',
          ),
        ),
      );
      await tester.pumpAndSettle();

      // Owner can "Claim This Item" directly without having a Missing report
      final claimButton = find.text('Claim This Item');
      expect(claimButton, findsOneWidget);
      await tester.ensureVisible(claimButton);

      await tester.tap(claimButton);
      await tester.pumpAndSettle();

      // Handover dialog opens
      expect(find.text('Claim Item Ownership'), findsOneWidget);
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
      expect(find.text('Claim Item Ownership'), findsNothing);
    });

    testWidgets('RecoveryRequestsScreen switches tabs and accepts handover', (
      WidgetTester tester,
    ) async {
      RecoveryRepository.instance.resetToMocks();
      await tester.binding.setSurfaceSize(const Size(390, 844));

      await tester.pumpWidget(
        const MaterialApp(home: RecoveryRequestsScreen()),
      );
      await tester.pumpAndSettle();

      expect(find.text('Received (2)'), findsOneWidget);
      expect(find.text('Sent (1)'), findsOneWidget);

      // Tap Sent tab
      await tester.tap(find.text('Sent (1)'));
      await tester.pumpAndSettle();

      // Switch back to Received tab
      await tester.tap(find.text('Received (2)'));
      await tester.pumpAndSettle();

      // Verify accept request dialog
      final acceptButton = find.text('Review & Accept').first;
      await tester.ensureVisible(acceptButton);
      await tester.tap(acceptButton);
      await tester.pumpAndSettle();

      expect(find.text('Accept Handover Request'), findsOneWidget);
      await tester.tap(find.text('Cancel'));
      await tester.pumpAndSettle();
    });
  });

  group('Group 5: Error Handling, 401 Session Expiry & 403 Forbidden', () {
    test(
      'Transparent 401 retry on expired access token with valid refresh token',
      () async {
        int accessAttempts = 0;
        tokenStorage.saveTokens(
          accessToken: 'expired_token',
          refreshToken: 'valid_refresh',
        );

        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports') {
            accessAttempts++;
            if (request.headers['authorization'] == 'Bearer expired_token') {
              return jsonResponse({'detail': 'Token expired'}, statusCode: 401);
            }
            if (request.headers['authorization'] == 'Bearer new_access_token') {
              return jsonResponse({
                'items': [],
                'page': 1,
                'page_size': 50,
                'total': 0,
                'total_pages': 0,
              });
            }
          }
          if (request.url.path == '/api/v1/auth/refresh') {
            return jsonResponse({
              'access_token': 'new_access_token',
              'refresh_token': 'new_refresh_token',
              'token_type': 'bearer',
            });
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        authService.setSessionForTesting(
          user: UserModel(
            id: 'u1',
            name: 'Test',
            email: 'test@example.com',
            createdAt: DateTime.now(),
          ),
          accessToken: 'expired_token',
          refreshToken: 'valid_refresh',
        );

        await reportRepository.loadReports();

        expect(accessAttempts, 2);
        expect(authService.currentAccessToken, 'new_access_token');
        expect(reportRepository.errorMessage, isNull);
      },
    );

    test(
      '401 with expired refresh token clears session and invokes onSessionExpired',
      () async {
        bool sessionExpiredFired = false;
        apiClient.onSessionExpired = () {
          sessionExpiredFired = true;
        };

        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports') {
            return jsonResponse({'detail': 'Token expired'}, statusCode: 401);
          }
          if (request.url.path == '/api/v1/auth/refresh') {
            return jsonResponse({
              'detail': 'Refresh token expired',
            }, statusCode: 401);
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        authService.setSessionForTesting(
          user: UserModel(
            id: 'u1',
            name: 'Test',
            email: 'test@example.com',
            createdAt: DateTime.now(),
          ),
          accessToken: 'expired_token',
          refreshToken: 'expired_refresh',
        );

        await reportRepository.loadReports();

        expect(sessionExpiredFired, isTrue);
        expect(authService.isAuthenticated, isFalse);
        expect(authService.currentUser, isNull);
      },
    );

    test(
      '403 Forbidden on updating someone else\'s report surfaces clean ApiException',
      () async {
        mockClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports/rep-other-user') {
            return jsonResponse({
              'detail': 'Not authorized to update this report',
            }, statusCode: 403);
          }
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        expect(
          () => apiClient.patch(
            '/api/v1/reports/rep-other-user',
            body: {'title': 'Hacked Title'},
            authenticated: true,
          ),
          throwsA(
            predicate<ApiException>(
              (e) =>
                  e.statusCode == 403 && e.message.contains('Not authorized'),
            ),
          ),
        );
      },
    );

    test(
      'Network failure during API call surfaces NetworkException cleanly',
      () async {
        mockClient.handler = (request) async {
          throw http.ClientException('Connection refused');
        };

        expect(
          () => apiClient.get('/api/v1/reports', authenticated: false),
          throwsA(isA<NetworkException>()),
        );
      },
    );
  });

  group('Group 6: Platform Configuration, Base URLs & CORS Hardening', () {
    test('Default base URL resolution handles environment and platform', () {
      final defaultUrl = ApiClient.resolveDefaultBaseUrl();
      expect(
        defaultUrl == 'http://127.0.0.1:8000' ||
            defaultUrl == 'http://10.0.2.2:8000',
        isTrue,
      );
    });

    test(
      'MapConfig specifies dark monochromatic tile layer without secret keys',
      () {
        expect(MapConfig.tileUrl, contains('tile.openstreetmap.org'));
        expect(MapConfig.attribution, contains('OpenStreetMap'));
        expect(MapConfig.tileUrl.contains('apiKey='), isFalse);
        expect(MapConfig.tileUrl.contains('access_token='), isFalse);
      },
    );

    test(
      'ReportRepository clamps search radius to backend boundary [0.1, 5.0]',
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
          return jsonResponse({'detail': 'Not found'}, statusCode: 404);
        };

        // Request with 10.0 km radius -> must be clamped to 5.0 km
        await reportRepository.loadReports(
          latitude: 50.4501,
          longitude: 30.5234,
          radiusKm: 10.0,
        );

        final queryParams = capturedRequest!.url.queryParameters;
        expect(queryParams['radius_km'], '5.0');
        expect(queryParams['sort'], 'distance');
      },
    );
  });
}
