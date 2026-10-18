import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:frontend/models/user_model.dart';
import 'package:frontend/services/api_client.dart';
import 'package:frontend/services/auth_service.dart';
import 'package:frontend/services/geocoding_service.dart';
import 'package:frontend/services/location_service.dart';
import 'package:frontend/services/report_repository.dart';
import 'package:frontend/services/token_storage.dart';
import 'package:frontend/ui/screens/create_report_screen.dart';
import 'package:frontend/ui/screens/map_screen.dart';
import 'package:frontend/ui/widgets/status_label.dart';
import 'package:http/http.dart' as http;
import 'package:latlong2/latlong.dart';

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
    latitude: 37.7749,
    longitude: -122.4194,
    accuracy: 10.0,
    isManual: false,
    label: 'San Francisco, CA',
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
      mockError = 'Location permission denied by user.';
      notifyListeners();
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
  TestWidgetsFlutterBinding.ensureInitialized();

  late MockHttpClient mockHttpClient;
  late InMemoryTokenStorage tokenStorage;
  late ApiClient apiClient;
  late AuthService authService;
  late ReportRepository reportRepository;
  late MockLocationService mockLocationService;

  setUp(() {
    mockHttpClient = MockHttpClient();
    tokenStorage = InMemoryTokenStorage();
    apiClient = ApiClient(
      baseUrl: 'http://127.0.0.1:8000',
      client: mockHttpClient,
    );
    authService = AuthService(client: apiClient, storage: tokenStorage);
    AuthService.setInstanceForTesting(authService);

    reportRepository = ReportRepository(
      apiClient: apiClient,
      authService: authService,
    );
    reportRepository.configure(client: apiClient, auth: authService);
    ReportRepository.setInstanceForTesting(reportRepository);

    mockLocationService = MockLocationService();
    LocationService.setInstanceForTesting(mockLocationService);

    GeocodingService.instance.clearCache();
  });

  group('Phase 6 Priority 1 & 3: GeocodingService Unit Tests', () {
    test('searchPlaces parses OpenStreetMap Nominatim responses', () async {
      mockHttpClient.handler = (request) async {
        if (request.url.host == 'nominatim.openstreetmap.org' &&
            request.url.path == '/search') {
          return jsonResponse([
            {
              'place_id': 12345,
              'display_name': 'Central Park, Manhattan, New York, USA',
              'name': 'Central Park',
              'lat': '40.785091',
              'lon': '-73.968285',
              'address': {
                'park': 'Central Park',
                'suburb': 'Manhattan',
                'city': 'New York',
                'state': 'New York',
              },
            },
          ]);
        }
        return jsonResponse([]);
      };

      final geocoding = GeocodingService(client: mockHttpClient);
      final results = await geocoding.searchPlaces('Central Park');

      expect(results.length, 1);
      expect(results.first.shortName, 'Central Park');
      expect(results.first.latitude, closeTo(40.785, 0.001));
      expect(results.first.longitude, closeTo(-73.968, 0.001));
    });

    test('reverseGeocode formats structured address cleanly', () async {
      mockHttpClient.handler = (request) async {
        if (request.url.host == 'nominatim.openstreetmap.org' &&
            request.url.path == '/reverse') {
          return jsonResponse({
            'display_name': '10, Downing Street, Westminster, London, UK',
            'address': {
              'house_number': '10',
              'road': 'Downing Street',
              'suburb': 'Westminster',
              'city': 'London',
            },
          });
        }
        return jsonResponse({}, statusCode: 404);
      };

      final geocoding = GeocodingService(client: mockHttpClient);
      final address = await geocoding.reverseGeocode(51.5034, -0.1276);

      expect(address, contains('10 Downing Street'));
      expect(address, contains('Westminster'));
      expect(address, contains('London'));
    });

    test(
      'reverseGeocode returns cached response on identical coordinates',
      () async {
        int requestCount = 0;
        mockHttpClient.handler = (request) async {
          requestCount++;
          return jsonResponse({
            'display_name': 'Broadway, New York, USA',
            'address': {'road': 'Broadway', 'city': 'New York'},
          });
        };

        final geocoding = GeocodingService(client: mockHttpClient);
        final addr1 = await geocoding.reverseGeocode(40.7128, -74.0060);
        final addr2 = await geocoding.reverseGeocode(40.7128, -74.0060);

        expect(addr1, addr2);
        expect(requestCount, 1);
      },
    );
  });

  group('Phase 6 Priority 1: Report Creation Location Selection', () {
    testWidgets(
      'Missing report opens ReportLocationPickerSheet and cancels without changes',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));

        await tester.pumpWidget(
          const MaterialApp(
            home: CreateReportScreen(initialStatus: ReportStatus.missing),
          ),
        );
        await tester.pumpAndSettle();

        final pickButton = find.text('Pick on Map');
        expect(pickButton, findsOneWidget);
        await tester.ensureVisible(pickButton);
        await tester.tap(pickButton);
        await tester.pumpAndSettle();

        // Picker sheet opens with title and controls
        expect(find.text('Select Location on Map'), findsOneWidget);
        expect(find.text('Confirm Location'), findsOneWidget);
        expect(find.byType(FlutterMap), findsOneWidget);

        // Close sheet
        await tester.tap(find.byIcon(Icons.close));
        await tester.pumpAndSettle();

        expect(find.text('Select Location on Map'), findsNothing);
      },
    );

    testWidgets(
      'Found report opens identical ReportLocationPickerSheet (reusable)',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));

        await tester.pumpWidget(
          const MaterialApp(
            home: CreateReportScreen(initialStatus: ReportStatus.found),
          ),
        );
        await tester.pumpAndSettle();

        final pickButton = find.text('Pick on Map');
        expect(pickButton, findsOneWidget);
        await tester.ensureVisible(pickButton);
        await tester.tap(pickButton);
        await tester.pumpAndSettle();

        expect(find.text('Select Location on Map'), findsOneWidget);
        expect(find.text('Confirm Location'), findsOneWidget);
        expect(find.byType(FlutterMap), findsOneWidget);
      },
    );

    testWidgets(
      'Confirming location returns exact coordinates and updates form state',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));

        await tester.pumpWidget(
          const MaterialApp(
            home: CreateReportScreen(initialStatus: ReportStatus.missing),
          ),
        );
        await tester.pumpAndSettle();

        await tester.ensureVisible(find.text('Pick on Map'));
        await tester.tap(find.text('Pick on Map'));
        await tester.pumpAndSettle();

        // Confirm Location button
        final confirmBtn = find.text('Confirm Location');
        expect(confirmBtn, findsOneWidget);
        await tester.tap(confirmBtn);
        await tester.pumpAndSettle();

        // The form now shows Confirmed location badge with Change and Clear actions
        expect(find.text('Select Location on Map'), findsNothing);
        expect(find.text('Change'), findsOneWidget);
        expect(find.text('Clear'), findsOneWidget);
        expect(
          find.byKey(const Key('create_report_latitude_field')),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'Clear button clears coordinates and restores Pick on Map action',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));

        await tester.pumpWidget(
          const MaterialApp(
            home: CreateReportScreen(initialStatus: ReportStatus.missing),
          ),
        );
        await tester.pumpAndSettle();

        // First pick a location
        await tester.ensureVisible(find.text('Pick on Map'));
        await tester.tap(find.text('Pick on Map'));
        await tester.pumpAndSettle();
        await tester.tap(find.text('Confirm Location'));
        await tester.pumpAndSettle();

        expect(find.text('Clear'), findsOneWidget);

        // Now tap Clear
        await tester.tap(find.text('Clear'));
        await tester.pumpAndSettle();

        // Coordinates cleared, Pick on Map restored
        expect(find.text('Pick on Map'), findsOneWidget);
        expect(find.text('Clear'), findsNothing);
      },
    );

    testWidgets(
      'Use GPS in CreateReportScreen populates coordinates with reverse geocoded address',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));

        mockHttpClient.handler = (request) async {
          if (request.url.path == '/reverse') {
            return jsonResponse({
              'display_name': '742 Evergreen Terrace, Springfield',
              'address': {
                'road': 'Evergreen Terrace',
                'house_number': '742',
                'city': 'Springfield',
              },
            });
          }
          return jsonResponse({});
        };
        GeocodingService.setInstanceForTesting(
          GeocodingService(client: mockHttpClient),
        );

        mockLocationService.mockPosition = const UserLocationData(
          latitude: 39.7817,
          longitude: -89.6501,
          accuracy: 8.0,
        );

        await tester.pumpWidget(
          const MaterialApp(
            home: CreateReportScreen(initialStatus: ReportStatus.missing),
          ),
        );
        await tester.pumpAndSettle();

        final gpsBtn = find.text('Use GPS');
        expect(gpsBtn, findsOneWidget);
        await tester.ensureVisible(gpsBtn);
        await tester.tap(gpsBtn);
        await tester.pumpAndSettle();

        expect(find.text('39.781700'), findsOneWidget);
        expect(find.text('-89.650100'), findsOneWidget);
        expect(find.text('Clear'), findsOneWidget);
      },
    );

    testWidgets(
      'Denied GPS permission does not crash or block manual location picking',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));

        mockLocationService.mockStatus = LocationPermissionStatus.denied;

        await tester.pumpWidget(
          const MaterialApp(
            home: CreateReportScreen(initialStatus: ReportStatus.missing),
          ),
        );
        await tester.pumpAndSettle();

        final gpsBtn = find.text('Use GPS');
        await tester.ensureVisible(gpsBtn);
        await tester.tap(gpsBtn);
        await tester.pumpAndSettle();

        // Error message shown or toast displayed, but Pick on Map remains interactive
        expect(find.text('Pick on Map'), findsOneWidget);
        await tester.tap(find.text('Pick on Map'));
        await tester.pumpAndSettle();

        expect(find.text('Select Location on Map'), findsOneWidget);
      },
    );

    testWidgets('Report creation does NOT alter the shared discovery anchor', (
      tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));

      // Discovery anchor set to Paris
      mockLocationService.setManualLocation(
        latitude: 48.8566,
        longitude: 2.3522,
        label: 'Paris, France',
      );

      await tester.pumpWidget(
        const MaterialApp(
          home: CreateReportScreen(initialStatus: ReportStatus.missing),
        ),
      );
      await tester.pumpAndSettle();

      // Open picker and confirm a point
      await tester.ensureVisible(find.text('Pick on Map'));
      await tester.tap(find.text('Pick on Map'));
      await tester.pumpAndSettle();
      await tester.tap(find.text('Confirm Location'));
      await tester.pumpAndSettle();

      // Shared discovery anchor must remain Paris!
      expect(
        mockLocationService.currentLocation?.latitude,
        closeTo(48.8566, 0.001),
      );
      expect(
        mockLocationService.currentLocation?.longitude,
        closeTo(2.3522, 0.001),
      );
      expect(mockLocationService.currentLocation?.label, 'Paris, France');
    });

    testWidgets(
      'Submitting report includes actual confirmed coordinates in API payload',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));

        Map<String, dynamic>? capturedPayload;
        mockHttpClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports' &&
              request.method == 'POST') {
            capturedPayload =
                jsonDecode((request as http.Request).body)
                    as Map<String, dynamic>;
            return jsonResponse({
              'id': 'REP-999',
              'title': 'Lost Keys',
              'description': 'Near station',
              'category': 'Electronics',
              'status': 'missing',
              'latitude': capturedPayload!['latitude'],
              'longitude': capturedPayload!['longitude'],
              'location_description': capturedPayload!['location_description'],
              'user_id': 'USR-1',
              'created_at': DateTime.now().toIso8601String(),
            }, statusCode: 201);
          }
          return jsonResponse({});
        };

        // Set user logged in
        authService.setSessionForTesting(
          user: UserModel(
            id: 'USR-1',
            email: 'test@example.com',
            name: 'Test User',
          ),
          accessToken: 'mock-test-token',
        );

        mockLocationService.mockPosition = const UserLocationData(
          latitude: 12.9716,
          longitude: 77.5946,
        );

        await tester.pumpWidget(
          const MaterialApp(
            home: CreateReportScreen(initialStatus: ReportStatus.missing),
          ),
        );
        await tester.pumpAndSettle();

        // Fill title
        final titleField = find.byKey(const Key('create_report_title_field'));
        await tester.ensureVisible(titleField);
        await tester.enterText(titleField, 'Lost Silver Watch');

        // Fill description
        final descField = find.byKey(
          const Key('create_report_description_field'),
        );
        await tester.ensureVisible(descField);
        await tester.enterText(
          descField,
          'Lost near the central transit plaza during afternoon.',
        );

        // Pick GPS location
        await tester.ensureVisible(find.text('Use GPS'));
        await tester.tap(find.text('Use GPS'));
        await tester.pumpAndSettle();

        // Submit report
        final submitBtn = find.text('Publish Missing Report');
        await tester.ensureVisible(submitBtn);
        await tester.tap(submitBtn);
        await tester.pumpAndSettle();

        // Verify payload
        expect(capturedPayload, isNotNull);
        expect(capturedPayload!['latitude'], closeTo(12.9716, 0.0001));
        expect(capturedPayload!['longitude'], closeTo(77.5946, 0.0001));
        expect(capturedPayload!['title'], 'Lost Silver Watch');
      },
    );
  });

  group('Phase 6 Priority 2: Map Section Discovery & Search Tests', () {
    testWidgets(
      'MapScreen place search triggers debounced suggestions and selecting one updates anchor',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));

        mockHttpClient.handler = (request) async {
          if (request.url.path == '/search') {
            return jsonResponse([
              {
                'place_id': 101,
                'display_name': 'Downtown Plaza, Seattle, WA, USA',
                'name': 'Downtown Plaza',
                'lat': '47.6062',
                'lon': '-122.3321',
                'address': {'suburb': 'Downtown', 'city': 'Seattle'},
              },
            ]);
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
          return jsonResponse({});
        };
        GeocodingService.setInstanceForTesting(
          GeocodingService(client: mockHttpClient),
        );

        await tester.pumpWidget(const MaterialApp(home: MapScreen()));
        await tester.pumpAndSettle();

        // Enter search text
        final searchField = find.byType(TextField);
        expect(searchField, findsOneWidget);
        await tester.enterText(searchField, 'Seattle');
        await tester.pump(const Duration(milliseconds: 400));
        await tester.pumpAndSettle();

        // Suggestions list appears
        expect(find.text('Downtown Plaza'), findsOneWidget);

        // Select suggestion
        await tester.tap(find.text('Downtown Plaza'));
        await tester.pumpAndSettle();

        // Anchor updated in LocationService
        expect(
          mockLocationService.currentLocation?.latitude,
          closeTo(47.6062, 0.001),
        );
        expect(
          mockLocationService.currentLocation?.longitude,
          closeTo(-122.3321, 0.001),
        );
      },
    );

    testWidgets(
      'Locate Me button centers map and updates reports around GPS position',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));

        int reportsQueryCount = 0;
        mockHttpClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports') {
            reportsQueryCount++;
            return jsonResponse({
              'items': [],
              'page': 1,
              'page_size': 50,
              'total': 0,
              'total_pages': 0,
            });
          }
          return jsonResponse({});
        };

        mockLocationService.mockPosition = const UserLocationData(
          latitude: 34.0522,
          longitude: -118.2437,
          label: 'Los Angeles, CA',
        );

        await tester.pumpWidget(const MaterialApp(home: MapScreen()));
        await tester.pumpAndSettle();

        // Tap Locate Me button
        final locateMeBtn = find.byTooltip('Locate Me');
        expect(locateMeBtn, findsOneWidget);
        await tester.tap(locateMeBtn);
        await tester.pumpAndSettle();

        expect(reportsQueryCount, greaterThanOrEqualTo(1));
      },
    );

    testWidgets('Search this area button updates anchor and reloads reports', (
      tester,
    ) async {
      await tester.binding.setSurfaceSize(const Size(390, 844));

      mockHttpClient.handler = (request) async {
        if (request.url.path == '/reverse') {
          return jsonResponse({
            'display_name': 'Austin Center, Austin, TX, USA',
            'address': {'city': 'Austin'},
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
        return jsonResponse({});
      };
      GeocodingService.setInstanceForTesting(
        GeocodingService(client: mockHttpClient),
      );

      await tester.pumpWidget(const MaterialApp(home: MapScreen()));
      await tester.pumpAndSettle();

      // Simulate map panning by finding the FlutterMap widget and executing onPositionChanged
      final flutterMapFinder = find.byType(FlutterMap);
      expect(flutterMapFinder, findsOneWidget);

      final flutterMap = tester.widget<FlutterMap>(flutterMapFinder);
      final onPosChanged = flutterMap.options.onPositionChanged;
      expect(onPosChanged, isNotNull);

      // Trigger position changed to a far point (Austin TX: 30.2672, -97.7431)
      final newCamera = MapCamera(
        crs: const Epsg3857(),
        minZoom: 3,
        maxZoom: 18,
        center: const LatLng(30.2672, -97.7431),
        zoom: 14,
        rotation: 0,
        nonRotatedSize: const Size(390, 844),
      );
      onPosChanged!(newCamera, true);
      await tester.pumpAndSettle();

      // "Search this area" floating button appears
      final searchThisAreaBtn = find.text('Search this area');
      expect(searchThisAreaBtn, findsOneWidget);

      // Tap "Search this area"
      await tester.tap(searchThisAreaBtn);
      await tester.pumpAndSettle();

      // Button disappears and anchor updated to Austin
      expect(find.text('Search this area'), findsNothing);
      expect(
        mockLocationService.currentLocation?.latitude,
        closeTo(30.2672, 0.001),
      );
      expect(
        mockLocationService.currentLocation?.longitude,
        closeTo(-97.7431, 0.001),
      );
    });

    testWidgets(
      'Tapping on radius chip preserves coordinates and reloads with new radius',
      (tester) async {
        await tester.binding.setSurfaceSize(const Size(390, 844));

        double? queriedRadius;
        mockHttpClient.handler = (request) async {
          if (request.url.path == '/api/v1/reports') {
            final radStr = request.url.queryParameters['radius_km'];
            if (radStr != null) {
              queriedRadius = double.tryParse(radStr);
            }
            return jsonResponse({
              'items': [],
              'page': 1,
              'page_size': 50,
              'total': 0,
              'total_pages': 0,
            });
          }
          return jsonResponse({});
        };

        await tester.pumpWidget(const MaterialApp(home: MapScreen()));
        await tester.pumpAndSettle();

        // Tap 2.0 km radius chip
        final chip2km = find.text('2.0 km');
        expect(chip2km, findsOneWidget);
        await tester.ensureVisible(chip2km);
        await tester.tap(chip2km);
        await tester.pumpAndSettle();

        expect(queriedRadius, closeTo(2.0, 0.05));
      },
    );
  });
}
