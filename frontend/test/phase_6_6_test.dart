import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/services/api_client.dart';
import 'package:frontend/services/auth_service.dart';
import 'package:frontend/services/location_service.dart';
import 'package:frontend/services/map_config.dart';
import 'package:frontend/services/report_repository.dart';
import 'package:frontend/services/token_storage.dart';
import 'package:frontend/ui/screens/create_report_screen.dart';
import 'package:frontend/ui/screens/map_screen.dart';
import 'package:frontend/ui/screens/report_details_screen.dart';
import 'package:frontend/ui/widgets/status_label.dart';
import 'package:http/http.dart' as http;

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

class MockLocationService extends ChangeNotifier implements LocationService {
  LocationPermissionStatus mockStatus = LocationPermissionStatus.granted;
  UserLocationData? mockPosition = const UserLocationData(
    latitude: 50.4501,
    longitude: 30.5234,
    accuracy: 10.0,
    isManual: false,
  );
  String? mockError;
  final bool _isLoading = false;

  @override
  bool get isLoading => _isLoading;

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
      isManual: true,
      label: label ?? 'Custom Point',
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

  group('Group 1: MapConfig & Monochromatic Theme Specifications', () {
    test(
      'MapConfig specifies tile layer with proper OpenStreetMap attribution',
      () {
        expect(
          MapConfig.darkTileUrl,
          'https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png',
        );
        expect(MapConfig.attribution, contains('OpenStreetMap'));
        expect(MapConfig.userAgent, 'com.boomerang.getme');
        expect(MapConfig.supportedRadiiKm, [0.5, 1.0, 2.0, 5.0]);
        expect(MapConfig.defaultRadiusKm, 5.0);
      },
    );

    test('MapConfig default viewport center coordinates are valid', () {
      expect(MapConfig.defaultViewportCenter.latitude, closeTo(50.4501, 0.001));
      expect(
        MapConfig.defaultViewportCenter.longitude,
        closeTo(30.5234, 0.001),
      );
      expect(MapConfig.minZoom, 3.0);
      expect(MapConfig.maxZoom, 18.0);
    });
  });

  group('Group 2: LocationService GPS, Permissions & Fallbacks', () {
    test('UserLocationData preserves manual anchor flag and label', () {
      const data = UserLocationData(
        latitude: 48.8566,
        longitude: 2.3522,
        isManual: true,
        label: 'Paris Center',
      );

      expect(data.latitude, 48.8566);
      expect(data.longitude, 2.3522);
      expect(data.isManual, isTrue);
      expect(data.label, 'Paris Center');
      expect(data.toLatLng().latitude, 48.8566);
      expect(data.toLatLng().longitude, 2.3522);
    });

    test(
      'LocationService setManualLocation updates state without hardware GPS',
      () {
        mockLocationService.setManualLocation(
          latitude: 40.7128,
          longitude: -74.0060,
          label: 'NYC Anchor',
        );

        expect(mockLocationService.currentLocation, isNotNull);
        expect(mockLocationService.currentLocation!.latitude, 40.7128);
        expect(mockLocationService.currentLocation!.longitude, -74.0060);
        expect(mockLocationService.currentLocation!.isManual, isTrue);
        expect(mockLocationService.currentLocation!.label, 'NYC Anchor');
      },
    );

    test('LocationService clearLocation resets location anchor', () {
      mockLocationService.setManualLocation(
        latitude: 40.7128,
        longitude: -74.0060,
      );
      expect(mockLocationService.currentLocation, isNotNull);

      mockLocationService.clearLocation();
      expect(mockLocationService.currentLocation, isNull);
    });

    test(
      'LocationService getCurrentPosition returns null on denied permission',
      () async {
        mockLocationService.mockStatus = LocationPermissionStatus.denied;
        mockLocationService.mockError = 'Permission denied by user.';

        final pos = await mockLocationService.getCurrentPosition();
        expect(pos, isNull);
        expect(mockLocationService.status, LocationPermissionStatus.denied);
        expect(mockLocationService.errorMessage, contains('denied'));
      },
    );
  });

  group('Group 3: ReportRepository Geo Radius Parameter Construction', () {
    test(
      'loadReports formats radius_km to 1 decimal place and clamps to 5.0 km',
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

        await reportRepository.loadReports(
          latitude: 50.4501,
          longitude: 30.5234,
          radiusKm: 7.5, // Exceeds 5.0 km backend limit -> must clamp to 5.0
        );

        expect(capturedRequest, isNotNull);
        final params = capturedRequest!.url.queryParameters;
        expect(params['latitude'], '50.4501');
        expect(params['longitude'], '30.5234');
        expect(params['radius_km'], '5.0');
        expect(params['sort'], 'distance');
        expect(reportRepository.searchLatitude, 50.4501);
        expect(reportRepository.searchLongitude, 30.5234);
        expect(reportRepository.searchRadiusKm, 5.0);
      },
    );

    test(
      'loadReports omits geo parameters when coordinates are null',
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

        await reportRepository.loadReports();

        expect(capturedRequest, isNotNull);
        final params = capturedRequest!.url.queryParameters;
        expect(params.containsKey('latitude'), isFalse);
        expect(params.containsKey('longitude'), isFalse);
        expect(params.containsKey('radius_km'), isFalse);
        expect(params['sort'], 'newest');
        expect(reportRepository.searchLatitude, isNull);
        expect(reportRepository.searchLongitude, isNull);
      },
    );

    test('clearGeoSearch resets repository search coordinates', () async {
      reportRepository.loadReports(
        latitude: 50.4501,
        longitude: 30.5234,
        radiusKm: 2.0,
      );

      reportRepository.clearGeoSearch();
      expect(reportRepository.searchLatitude, isNull);
      expect(reportRepository.searchLongitude, isNull);
      expect(reportRepository.searchRadiusKm, isNull);
    });

    test('loadReports handles geo error and sets errorMessage', () async {
      mockClient.handler = (request) async {
        if (request.url.path == '/api/v1/reports') {
          return jsonResponse({
            'detail': 'Invalid radius_km: must be <= 5.0',
          }, statusCode: 422);
        }
        return jsonResponse({'detail': 'Not found'}, statusCode: 404);
      };

      await reportRepository.loadReports(
        latitude: 50.4501,
        longitude: 30.5234,
        radiusKm: 2.0,
      );

      expect(reportRepository.errorMessage, isNotNull);
      expect(reportRepository.isLoading, isFalse);
    });
  });

  group('Group 4: MapScreen Real Map & Monochromatic Markers UI', () {
    testWidgets('MapScreen renders FlutterMap canvas and search controls', (
      WidgetTester tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));

      mockClient.handler = (request) async {
        if (request.url.path == '/api/v1/reports') {
          return jsonResponse({
            'items': [
              {
                'id': 'geo-rep-01',
                'created_by_user_id': 'u1',
                'type': 'MISSING',
                'title': 'Tactical Backpack',
                'description': 'Black cordura pack',
                'category': 'BAG',
                'latitude': 50.4520,
                'longitude': 30.5250,
                'event_time': '2026-10-12T12:00:00Z',
                'reward_amount': 75.0,
                'status': 'OPEN',
                'created_at': '2026-10-12T12:00:00Z',
                'updated_at': '2026-10-12T12:00:00Z',
                'distance_km': 0.3,
                'images': [],
              },
              {
                'id': 'geo-rep-02',
                'created_by_user_id': 'u2',
                'type': 'FOUND',
                'title': 'Car Key Fob',
                'description': 'Audi smart key',
                'category': 'KEYS',
                'latitude': 50.4480,
                'longitude': 30.5210,
                'event_time': '2026-10-12T13:00:00Z',
                'reward_amount': null,
                'status': 'OPEN',
                'created_at': '2026-10-12T13:00:00Z',
                'updated_at': '2026-10-12T13:00:00Z',
                'distance_km': 0.6,
                'images': [],
              },
            ],
            'page': 1,
            'page_size': 50,
            'total': 2,
            'total_pages': 1,
          });
        }
        return jsonResponse({'detail': 'Not found'}, statusCode: 404);
      };

      await tester.pumpWidget(const MaterialApp(home: MapScreen()));
      await tester.pumpAndSettle();

      // Real map canvas is rendered
      expect(find.byType(FlutterMap), findsOneWidget);
      expect(find.byType(TileLayer), findsOneWidget);
      expect(find.byType(MarkerLayer), findsOneWidget);

      // Search bar and controls are rendered
      expect(find.byType(TextField), findsOneWidget);
      expect(find.byIcon(Icons.tune), findsOneWidget);
      expect(find.byIcon(Icons.near_me), findsOneWidget);

      // Filter chips are rendered
      expect(find.text('All'), findsOneWidget);
      expect(find.text('Missing'), findsOneWidget);
      expect(find.text('Found'), findsOneWidget);

      // Radius chips are rendered
      expect(find.text('0.5 km'), findsOneWidget);
      expect(find.text('1.0 km'), findsOneWidget);
      expect(find.text('2.0 km'), findsOneWidget);
      expect(find.text('5.0 km'), findsOneWidget);
    });

    testWidgets('Tapping marker displays preview card and opens details', (
      WidgetTester tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));

      mockClient.handler = (request) async {
        if (request.url.path == '/api/v1/reports') {
          return jsonResponse({
            'items': [
              {
                'id': 'geo-marker-01',
                'created_by_user_id': 'u1',
                'type': 'MISSING',
                'title': 'Field Notebook',
                'description': 'Black moleskine with sketches',
                'category': 'DOCUMENTS',
                'latitude': 50.4505,
                'longitude': 30.5238,
                'event_time': '2026-10-12T14:00:00Z',
                'reward_amount': 50.0,
                'status': 'OPEN',
                'created_at': '2026-10-12T14:00:00Z',
                'updated_at': '2026-10-12T14:00:00Z',
                'distance_km': 0.2,
                'images': [],
              },
            ],
            'page': 1,
            'page_size': 50,
            'total': 1,
            'total_pages': 1,
          });
        }
        return jsonResponse({'detail': 'Not found'}, statusCode: 404);
      };

      await tester.pumpWidget(const MaterialApp(home: MapScreen()));
      await tester.pumpAndSettle();

      // Find the marker by Semantics label
      final markerFinder = find.bySemanticsLabel(
        'Map marker for Field Notebook, status: Missing',
      );
      expect(markerFinder, findsOneWidget);

      // Tap the marker to select it
      await tester.tap(markerFinder);
      await tester.pumpAndSettle();

      // Preview card is displayed
      expect(find.text('Field Notebook'), findsWidgets);
      expect(find.text('View Details'), findsOneWidget);

      // Tap 'View Details' button on preview card
      await tester.tap(find.text('View Details'));
      await tester.pumpAndSettle();

      // ReportDetailsScreen is opened
      expect(find.byType(ReportDetailsScreen), findsOneWidget);
    });

    testWidgets('Tapping radius chip updates search radius', (
      WidgetTester tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));

      http.Request? latestRequest;
      mockClient.handler = (request) async {
        if (request.url.path == '/api/v1/reports') {
          latestRequest = request as http.Request;
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

      await tester.pumpWidget(const MaterialApp(home: MapScreen()));
      await tester.pumpAndSettle();

      // Tap 5.0 km radius chip
      await tester.ensureVisible(find.text('5.0 km'));
      await tester.tap(find.text('5.0 km'));
      await tester.pumpAndSettle();

      // Anchor was set by mockLocationService
      expect(latestRequest?.url.queryParameters['radius_km'], '5.0');
    });

    testWidgets('Locate Me button calls GPS and centers position', (
      WidgetTester tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));

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

      await tester.pumpWidget(const MaterialApp(home: MapScreen()));
      await tester.pumpAndSettle();

      // Tap Locate Me button
      final locateButton = find.byTooltip('Locate Me');
      expect(locateButton, findsOneWidget);
      await tester.tap(locateButton);
      await tester.pumpAndSettle();

      // SnackBar shows confirmation
      expect(
        find.text('Position located via GPS. Updating nearby reports.'),
        findsOneWidget,
      );
    });

    testWidgets(
      'Permission failure opens location notice sheet with manual fallback',
      (WidgetTester tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));

        mockLocationService.mockStatus = LocationPermissionStatus.denied;
        mockLocationService.mockError =
            'Location permission denied. You can select your position manually on the map.';

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

        await tester.pumpWidget(const MaterialApp(home: MapScreen()));
        await tester.pumpAndSettle();

        // Tap Locate Me button
        await tester.tap(find.byTooltip('Locate Me'));
        await tester.pumpAndSettle();

        // Bottom sheet with explanation and manual tap fallback appears
        expect(find.text('Location Service Notice'), findsOneWidget);
        expect(find.text('Tap Map Manually'), findsOneWidget);
      },
    );
  });

  group(
    'Group 5: CreateReportScreen Geolocation & Pick on Map Integration',
    () {
      testWidgets(
        'Use GPS button populates coordinates in CreateReportScreen',
        (WidgetTester tester) async {
          await tester.binding.setSurfaceSize(const Size(390, 844));

          mockLocationService.mockPosition = const UserLocationData(
            latitude: 50.4550,
            longitude: 30.5280,
          );

          await tester.pumpWidget(
            const MaterialApp(
              home: CreateReportScreen(initialStatus: ReportStatus.missing),
            ),
          );
          await tester.pumpAndSettle();

          // Verify 'Use GPS' button is present
          final gpsButton = find.text('Use GPS');
          expect(gpsButton, findsOneWidget);

          await tester.ensureVisible(gpsButton);
          await tester.tap(gpsButton);
          await tester.pumpAndSettle();

          // Verify coordinates were populated
          final latField = find.byKey(
            const Key('create_report_latitude_field'),
          );
          expect(latField, findsOneWidget);
          expect(find.text('50.455000'), findsOneWidget);
          expect(find.text('30.528000'), findsOneWidget);
        },
      );

      testWidgets(
        'Pick on Map button opens map picker sheet with Confirm button',
        (WidgetTester tester) async {
          await tester.binding.setSurfaceSize(const Size(390, 844));

          await tester.pumpWidget(
            const MaterialApp(
              home: CreateReportScreen(initialStatus: ReportStatus.missing),
            ),
          );
          await tester.pumpAndSettle();

          // Verify 'Pick on Map' button is present
          final pickOnMapButton = find.text('Pick on Map');
          expect(pickOnMapButton, findsOneWidget);

          await tester.ensureVisible(pickOnMapButton);
          await tester.tap(pickOnMapButton);
          await tester.pumpAndSettle();

          // Modal sheet opens with FlutterMap and Confirm Location button
          expect(find.text('Select Location on Map'), findsOneWidget);
          expect(find.text('Confirm Location'), findsOneWidget);

          // Confirm selection
          await tester.tap(find.text('Confirm Location'));
          await tester.pumpAndSettle();

          // Modal closes
          expect(find.text('Select Location on Map'), findsNothing);
        },
      );
    },
  );
}
