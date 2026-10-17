import 'dart:typed_data';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:frontend/services/api_client.dart';
import 'package:frontend/services/auth_service.dart';
import 'package:frontend/services/report_repository.dart';
import 'package:frontend/services/token_storage.dart';
import 'package:frontend/ui/widgets/status_label.dart';

void main() {
  const liveBaseUrl = 'http://127.0.0.1:8000';
  late ApiClient liveApiClient;
  late TokenStorage tokenStorage;
  late AuthService liveAuthService;
  late ReportRepository liveReportRepository;

  final timestamp = DateTime.now().millisecondsSinceEpoch;
  final testEmail = 'flutter_live_$timestamp@example.com';
  final testName = 'Flutter Smoke Tester $timestamp';
  const testPassword = 'SecurePassword123!';

  setUpAll(() {
    tokenStorage = InMemoryTokenStorage();
    liveApiClient = ApiClient(baseUrl: liveBaseUrl, client: http.Client());
    liveAuthService = AuthService(client: liveApiClient, storage: tokenStorage);
    liveReportRepository = ReportRepository(
      apiClient: liveApiClient,
      authService: liveAuthService,
    );
  });

  tearDownAll(() {
    liveApiClient.client.close();
  });

  group('Live Backend Flutter Integration Smoke Test', () {
    test('1. Backend /health is reachable and database is healthy', () async {
      final res = await liveApiClient.get('/health', authenticated: false);
      expect(res, isA<Map<String, dynamic>>());
      final map = res as Map<String, dynamic>;
      expect(map['status'], 'ok');
      expect(map['database'], 'ok');
    });

    test('2. AuthService registers a new user against live backend', () async {
      final user = await liveAuthService.register(
        email: testEmail,
        name: testName,
        password: testPassword,
      );
      expect(user.id, isNotEmpty);
      expect(user.email, testEmail);
      expect(user.name, testName);
    });

    test(
      '3. AuthService logs in and fetches user profile /api/v1/users/me',
      () async {
        final loggedInUser = await liveAuthService.login(
          email: testEmail,
          password: testPassword,
        );
        expect(liveAuthService.isAuthenticated, isTrue);
        expect(loggedInUser.email, testEmail);
        expect(liveAuthService.currentUser?.id, loggedInUser.id);
        expect(liveApiClient.tokenProvider?.call(), isNotNull);
      },
    );

    test(
      '4. ReportRepository creates a live MISSING report with float coordinates',
      () async {
        final report = await liveReportRepository.createReport(
          title: 'Flutter Live Drone Item $timestamp',
          category: 'Electronics',
          description:
              'Black carbon-fiber quadcopter drone verified during live smoke test.',
          locationDescription: 'Kyiv Central Park Sector',
          dateTime: DateTime.now(),
          status: ReportStatus.missing,
          reward: '\$150',
          latitude: 50.4501,
          longitude: 30.5234,
        );

        expect(report.id, isNotEmpty);
        expect(report.title, 'Flutter Live Drone Item $timestamp');
        expect(report.status, ReportStatus.missing);
        expect(report.reward, '\$150');
        expect(report.createdByUserId, liveAuthService.currentUser?.id);
      },
    );

    test(
      '5. ReportRepository loads live reports and isolates userReports',
      () async {
        await liveReportRepository.loadReports(forceRefresh: true);
        expect(liveReportRepository.reports, isNotEmpty);
        expect(liveReportRepository.errorMessage, isNull);

        final userReports = liveReportRepository.userReports;
        expect(userReports, isNotEmpty);
        expect(
          userReports.any(
            (r) => r.title == 'Flutter Live Drone Item $timestamp',
          ),
          isTrue,
        );
      },
    );

    test(
      '6. ReportRepository fetches single report by UUID from live backend',
      () async {
        final created = liveReportRepository.userReports.firstWhere(
          (r) => r.title == 'Flutter Live Drone Item $timestamp',
        );

        final fetched = await liveReportRepository.fetchReportById(created.id);
        expect(fetched, isNotNull);
        expect(fetched?.id, created.id);
        expect(fetched?.title, created.title);
        expect(fetched?.category, 'Electronics');
      },
    );

    test(
      '7. ReportRepository creates report with image and uploads multipart image to S3',
      () async {
        // 1x1 minimal JPEG bytes
        final dummyJpeg = Uint8List.fromList([
          0xff,
          0xd8,
          0xff,
          0xe0,
          0x00,
          0x10,
          0x4a,
          0x46,
          0x49,
          0x46,
          0x00,
          0x01,
          0x01,
          0x01,
          0x00,
          0x48,
          0x00,
          0x48,
          0x00,
          0x00,
          0xff,
          0xdb,
          0x00,
          0x43,
          0x00,
          0x08,
          0x06,
          0x06,
          0x07,
          0x06,
          0x05,
          0x08,
          0x07,
          0x07,
          0x07,
          0x09,
          0x09,
          0x08,
          0x0a,
          0x0c,
          0x14,
          0x0d,
          0x0c,
          0x0b,
          0x0b,
          0x0c,
          0x19,
          0x12,
          0x13,
          0x0f,
          0x14,
          0x1d,
          0x1a,
          0x1f,
          0x1e,
          0x1d,
          0x1a,
          0x1c,
          0x1c,
          0x20,
          0x24,
          0x2e,
          0x27,
          0x20,
          0x22,
          0x2c,
          0x23,
          0x1c,
          0x1c,
          0x28,
          0x37,
          0x29,
          0x30,
          0x31,
          0x34,
          0x34,
          0x34,
          0x1f,
          0x27,
          0x39,
          0x3d,
          0x38,
          0x32,
          0x3c,
          0x2e,
          0x33,
          0x34,
          0x32,
          0xff,
          0xc0,
          0x00,
          0x0b,
          0x08,
          0x00,
          0x01,
          0x00,
          0x01,
          0x01,
          0x01,
          0x11,
          0x00,
          0xff,
          0xc4,
          0x00,
          0x1f,
          0x00,
          0x00,
          0x01,
          0x05,
          0x01,
          0x01,
          0x01,
          0x01,
          0x01,
          0x01,
          0x00,
          0x00,
          0x00,
          0x00,
          0x00,
          0x00,
          0x00,
          0x00,
          0x01,
          0x02,
          0x03,
          0x04,
          0x05,
          0x06,
          0x07,
          0x08,
          0x09,
          0x0a,
          0x0b,
          0xff,
          0xda,
          0x00,
          0x08,
          0x01,
          0x01,
          0x00,
          0x00,
          0x3f,
          0x00,
          0xbf,
          0x00,
          0xff,
          0xd9,
        ]);

        final reportWithImg = await liveReportRepository.createReport(
          title: 'Flutter Live Photo Report $timestamp',
          category: 'Bag',
          description: 'Timbuk2 messenger bag with uploaded photo telemetry.',
          locationDescription: 'Central Station Track 3',
          dateTime: DateTime.now(),
          status: ReportStatus.found,
          latitude: 50.4404,
          longitude: 30.4894,
          photoBytesList: [dummyJpeg],
        );

        expect(reportWithImg.id, isNotEmpty);
        expect(reportWithImg.images, isNotEmpty);
        expect(reportWithImg.images.first.id, isNotEmpty);
      },
    );

    test(
      '8. AuthService logs out and revokes refresh session on live backend',
      () async {
        await liveAuthService.logout();
        expect(liveAuthService.isAuthenticated, isFalse);
        expect(liveAuthService.currentUser, isNull);
        expect(liveApiClient.tokenProvider?.call(), isNull);
      },
    );
  });
}
