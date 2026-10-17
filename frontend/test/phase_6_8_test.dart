import 'dart:convert';
import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;

import 'package:frontend/models/recovery_request_model.dart';
import 'package:frontend/services/api_client.dart';
import 'package:frontend/services/auth_service.dart';
import 'package:frontend/services/recovery_repository.dart';
import 'package:frontend/services/token_storage.dart';
import 'package:frontend/ui/screens/recovery_requests_screen.dart';
import 'package:frontend/ui/screens/report_details_screen.dart';
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
        headers: {'content-type': 'application/json'},
      ),
    );
  }
}

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  late InMemoryTokenStorage tokenStorage;
  late ApiClient apiClient;
  late MockHttpClient mockHttp;
  late AuthService authService;
  late RecoveryRepository recoveryRepo;

  setUp(() {
    tokenStorage = InMemoryTokenStorage();
    tokenStorage.saveTokens(
      accessToken: 'valid_test_access_token',
      refreshToken: 'valid_test_refresh_token',
    );

    mockHttp = MockHttpClient();
    apiClient = ApiClient(
      baseUrl: 'http://127.0.0.1:8000',
      client: mockHttp,
      tokenProvider: () => 'valid_test_access_token',
    );

    authService = AuthService(client: apiClient, storage: tokenStorage);
    AuthService.setInstanceForTesting(authService);

    recoveryRepo = RecoveryRepository(client: apiClient);
    RecoveryRepository.setInstanceForTesting(recoveryRepo);
  });

  group('Phase 6.8: RecoveryRequestModel JSON Tests', () {
    test('Model parses complete nested backend JSON payload', () {
      final json = {
        'id': 'rec-1234',
        'report_id': 'rep-5678',
        'requester_id': 'usr-0001',
        'recipient_id': 'usr-0002',
        'status': 'PENDING',
        'message': 'I have your item at the counter',
        'verification_response': 'Green lining verified',
        'created_at': '2026-10-14T10:00:00Z',
        'updated_at': '2026-10-14T10:30:00Z',
        'report': {
          'id': 'rep-5678',
          'title': 'Space Black MacBook',
          'type': 'MISSING',
          'category': 'ELECTRONICS',
          'status': 'ACTIVE',
        },
        'requester': {
          'id': 'usr-0001',
          'name': 'Finder Bob',
          'email': 'bob@example.com',
        },
        'recipient': {
          'id': 'usr-0002',
          'name': 'Owner Alice',
          'email': 'alice@example.com',
        },
      };

      final model = RecoveryRequestModel.fromJson(json);

      expect(model.id, 'rec-1234');
      expect(model.reportId, 'rep-5678');
      expect(model.status, 'pending');
      expect(model.message, 'I have your item at the counter');
      expect(model.verificationResponse, 'Green lining verified');
      expect(model.reportTitle, 'Space Black MacBook');
      expect(model.reportType, 'MISSING');
      expect(model.requesterName, 'Finder Bob');
      expect(model.recipientName, 'Owner Alice');
      expect(model.requesterEmail, 'bob@example.com');
      expect(model.recipientEmail, 'alice@example.com');
    });

    test('Model serializes back to JSON', () {
      final model = RecoveryRequestModel(
        id: 'rec-1234',
        reportId: 'rep-5678',
        requesterId: 'usr-0001',
        recipientId: 'usr-0002',
        status: 'pending',
        message: 'Hello',
        createdAt: DateTime.parse('2026-10-14T10:00:00Z'),
        updatedAt: DateTime.parse('2026-10-14T10:00:00Z'),
      );

      final json = model.toJson();
      expect(json['id'], 'rec-1234');
      expect(json['report_id'], 'rep-5678');
      expect(json['status'], 'PENDING');
      expect(json['message'], 'Hello');
    });
  });

  group('Phase 6.8: RecoveryRepository Live API Integration Tests', () {
    test('loadRequests queries both received and sent endpoints', () async {
      final requestedUrls = <String>[];

      mockHttp.handler = (req) async {
        requestedUrls.add(req.url.toString());
        if (req.url.path.contains('recovery-requests') &&
            req.url.query.contains('type=received')) {
          return http.StreamedResponse(
            Stream.value(
              utf8.encode(
                jsonEncode({
                  'items': [
                    {
                      'id': 'req-rec-1',
                      'report_id': 'rep-1',
                      'requester_id': 'usr-1',
                      'recipient_id': 'usr-me',
                      'status': 'PENDING',
                      'created_at': '2026-10-14T12:00:00Z',
                      'updated_at': '2026-10-14T12:00:00Z',
                      'report': {'title': 'Received Item', 'type': 'MISSING'},
                      'requester': {'name': 'Finder 1', 'email': 'f1@test.com'},
                    },
                  ],
                  'total': 1,
                  'page': 1,
                  'page_size': 20,
                  'total_pages': 1,
                }),
              ),
            ),
            200,
            headers: {'content-type': 'application/json'},
          );
        } else if (req.url.path.contains('recovery-requests') &&
            req.url.query.contains('type=sent')) {
          return http.StreamedResponse(
            Stream.value(
              utf8.encode(
                jsonEncode({
                  'items': [
                    {
                      'id': 'req-sent-1',
                      'report_id': 'rep-2',
                      'requester_id': 'usr-me',
                      'recipient_id': 'usr-2',
                      'status': 'ACCEPTED',
                      'created_at': '2026-10-14T11:00:00Z',
                      'updated_at': '2026-10-14T11:00:00Z',
                      'report': {'title': 'Sent Item', 'type': 'FOUND'},
                      'recipient': {'name': 'Owner 2', 'email': 'o2@test.com'},
                    },
                  ],
                  'total': 1,
                  'page': 1,
                  'page_size': 20,
                  'total_pages': 1,
                }),
              ),
            ),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        return http.StreamedResponse(Stream.value(utf8.encode('{}')), 200);
      };

      recoveryRepo.configure(client: apiClient);
      await recoveryRepo.loadRequests();

      expect(requestedUrls.any((u) => u.contains('type=received')), isTrue);
      expect(requestedUrls.any((u) => u.contains('type=sent')), isTrue);
      expect(recoveryRepo.receivedRequests.length, 1);
      expect(recoveryRepo.receivedRequests.first.reportTitle, 'Received Item');
      expect(recoveryRepo.sentRequests.length, 1);
      expect(recoveryRepo.sentRequests.first.reportTitle, 'Sent Item');
      expect(recoveryRepo.sentRequests.first.status, 'accepted');
    });

    test(
      'createRecoveryRequest sends POST and prepends to sentRequests',
      () async {
        Map<String, dynamic>? postedBody;

        mockHttp.handler = (req) async {
          if (req.method == 'POST' &&
              req.url.path.contains('recovery-requests')) {
            final bodyStr = await req.finalize().bytesToString();
            postedBody = jsonDecode(bodyStr) as Map<String, dynamic>;
            return http.StreamedResponse(
              Stream.value(
                utf8.encode(
                  jsonEncode({
                    'id': 'req-new-99',
                    'report_id': 'rep-target',
                    'requester_id': 'usr-me',
                    'recipient_id': 'usr-owner',
                    'status': 'PENDING',
                    'message': 'Direct handover proposal',
                    'created_at': '2026-10-14T15:00:00Z',
                    'updated_at': '2026-10-14T15:00:00Z',
                    'report': {'title': 'Target Item', 'type': 'MISSING'},
                  }),
                ),
              ),
              201,
              headers: {'content-type': 'application/json'},
            );
          }
          return http.StreamedResponse(Stream.value(utf8.encode('{}')), 200);
        };

        recoveryRepo.configure(client: apiClient);
        final created = await recoveryRepo.createRecoveryRequest(
          reportId: 'rep-target',
          message: 'Direct handover proposal',
        );

        expect(postedBody?['report_id'], 'rep-target');
        expect(postedBody?['message'], 'Direct handover proposal');
        expect(created.id, 'req-new-99');
        expect(recoveryRepo.sentRequests.first.id, 'req-new-99');
      },
    );

    test('updateRequestStatus sends PATCH and updates local model', () async {
      Map<String, dynamic>? patchBody;

      mockHttp.handler = (req) async {
        if (req.method == 'PATCH' && req.url.path.contains('req-rec-1')) {
          final bodyStr = await req.finalize().bytesToString();
          patchBody = jsonDecode(bodyStr) as Map<String, dynamic>;
          return http.StreamedResponse(
            Stream.value(
              utf8.encode(
                jsonEncode({
                  'id': 'req-rec-1',
                  'report_id': 'rep-1',
                  'requester_id': 'usr-1',
                  'recipient_id': 'usr-me',
                  'status': 'ACCEPTED',
                  'verification_response': 'Safe handover at Podil',
                  'created_at': '2026-10-14T12:00:00Z',
                  'updated_at': '2026-10-14T12:30:00Z',
                }),
              ),
            ),
            200,
            headers: {'content-type': 'application/json'},
          );
        }
        return http.StreamedResponse(Stream.value(utf8.encode('{}')), 200);
      };

      recoveryRepo.configure(client: apiClient);
      final updated = await recoveryRepo.updateRequestStatus(
        requestId: 'req-rec-1',
        status: 'ACCEPTED',
        verificationResponse: 'Safe handover at Podil',
      );

      expect(patchBody?['status'], 'ACCEPTED');
      expect(patchBody?['verification_response'], 'Safe handover at Podil');
      expect(updated.status, 'accepted');
    });

    test('API conflict on duplicate request throws clean ApiException', () async {
      mockHttp.handler = (req) async {
        return http.StreamedResponse(
          Stream.value(
            utf8.encode(
              jsonEncode({
                'detail':
                    'A pending or accepted recovery request already exists for this report',
              }),
            ),
          ),
          409,
          headers: {'content-type': 'application/json'},
        );
      };

      recoveryRepo.configure(client: apiClient);
      expect(
        () => recoveryRepo.createRecoveryRequest(reportId: 'rep-dup'),
        throwsA(
          isA<ApiException>().having((e) => e.statusCode, 'statusCode', 409),
        ),
      );
    });

    test(
      'API bad request on self-report recovery throws clean ApiException',
      () async {
        mockHttp.handler = (req) async {
          return http.StreamedResponse(
            Stream.value(
              utf8.encode(
                jsonEncode({
                  'detail':
                      'Cannot initiate recovery request on your own report',
                }),
              ),
            ),
            400,
            headers: {'content-type': 'application/json'},
          );
        };

        recoveryRepo.configure(client: apiClient);
        expect(
          () => recoveryRepo.createRecoveryRequest(reportId: 'rep-own'),
          throwsA(
            isA<ApiException>().having((e) => e.statusCode, 'statusCode', 400),
          ),
        );
      },
    );
  });

  group('Phase 6.8: SecurePlatformTokenStorage Tests', () {
    test(
      'Fallback mechanism operates gracefully without native channels',
      () async {
        final secureStorage = SecurePlatformTokenStorage();

        await secureStorage.saveTokens(
          accessToken: 'sec_access_token_123',
          refreshToken: 'sec_refresh_token_456',
        );

        final access = await secureStorage.getAccessToken();
        final refresh = await secureStorage.getRefreshToken();

        expect(access, 'sec_access_token_123');
        expect(refresh, 'sec_refresh_token_456');

        await secureStorage.clearTokens();
        expect(await secureStorage.getAccessToken(), isNull);
        expect(await secureStorage.getRefreshToken(), isNull);
      },
    );
  });

  group('Phase 6.8: UI & Recovery Request Handover Workflows', () {
    testWidgets(
      'ReportDetailsScreen dispatches real recovery request on button tap',
      (WidgetTester tester) async {
        String? requestedReportId;

        mockHttp.handler = (req) async {
          if (req.method == 'POST' &&
              req.url.path.contains('recovery-requests')) {
            final bodyStr = await req.finalize().bytesToString();
            final json = jsonDecode(bodyStr) as Map<String, dynamic>;
            requestedReportId = json['report_id'] as String;
            return http.StreamedResponse(
              Stream.value(
                utf8.encode(
                  jsonEncode({
                    'id': 'rec-live-101',
                    'report_id': requestedReportId,
                    'requester_id': 'usr-me',
                    'recipient_id': 'usr-owner',
                    'status': 'PENDING',
                    'created_at': '2026-10-14T10:00:00Z',
                    'updated_at': '2026-10-14T10:00:00Z',
                  }),
                ),
              ),
              201,
              headers: {'content-type': 'application/json'},
            );
          }
          if (req.url.path.contains('/api/v1/reports')) {
            return http.StreamedResponse(
              Stream.value(
                utf8.encode(
                  jsonEncode({
                    'id': 'rep-live-test-uuid',
                    'title': 'MacBook Air M2',
                    'description': 'Silver MacBook in sleeve',
                    'category': 'Electronics',
                    'report_type': 'MISSING',
                    'status': 'ACTIVE',
                    'location_description': 'Podil Metro',
                    'latitude': 50.4501,
                    'longitude': 30.5234,
                    'reward_amount': 100.0,
                    'user_id': 'usr-other',
                    'created_at': '2026-10-14T09:00:00Z',
                    'updated_at': '2026-10-14T09:00:00Z',
                    'images': [],
                  }),
                ),
              ),
              200,
              headers: {'content-type': 'application/json'},
            );
          }
          return http.StreamedResponse(Stream.value(utf8.encode('{}')), 200);
        };

        recoveryRepo.configure(client: apiClient);

        await tester.pumpWidget(
          MaterialApp(
            home: ReportDetailsScreen(
              reportId: 'rep-live-test-uuid',
              title: 'MacBook Air M2',
              category: 'Electronics',
              distance: '0.5 km',
              timeAgo: '1h ago',
              status: ReportStatus.missing,
              reward: '100',
              locationDescription: 'Podil Metro',
              description: 'Silver MacBook in sleeve',
            ),
          ),
        );
        await tester.pumpAndSettle();

        final button = find.text('I Found This Item');
        await tester.ensureVisible(button);
        await tester.tap(button);
        await tester.pumpAndSettle();

        expect(find.text('Initiate Handover Contact'), findsOneWidget);

        final sendButton = find.text('Send Recovery Request');
        await tester.tap(sendButton);
        await tester.pumpAndSettle();

        expect(requestedReportId, 'rep-live-test-uuid');
        expect(
          find.text('Recovery request sent for MacBook Air M2.'),
          findsOneWidget,
        );
      },
    );

    testWidgets(
      'RecoveryRequestsScreen loads real requests from live repository',
      (WidgetTester tester) async {
        mockHttp.handler = (req) async {
          if (req.url.query.contains('type=received')) {
            return http.StreamedResponse(
              Stream.value(
                utf8.encode(
                  jsonEncode({
                    'items': [
                      {
                        'id': '#REQ-9999',
                        'report_id': 'rep-live-1',
                        'requester_id': 'usr-live-1',
                        'recipient_id': 'usr-me',
                        'status': 'PENDING',
                        'message': 'Live verified handover request',
                        'created_at': '2026-10-14T12:00:00Z',
                        'updated_at': '2026-10-14T12:00:00Z',
                        'report': {
                          'title': 'Titanium Watch',
                          'type': 'MISSING',
                        },
                        'requester': {
                          'name': 'Danylo K.',
                          'email': 'danylo@example.com',
                        },
                      },
                    ],
                    'total': 1,
                    'page': 1,
                    'page_size': 20,
                    'total_pages': 1,
                  }),
                ),
              ),
              200,
              headers: {'content-type': 'application/json'},
            );
          } else if (req.url.query.contains('type=sent')) {
            return http.StreamedResponse(
              Stream.value(
                utf8.encode(
                  jsonEncode({
                    'items': [],
                    'total': 0,
                    'page': 1,
                    'page_size': 20,
                    'total_pages': 0,
                  }),
                ),
              ),
              200,
              headers: {'content-type': 'application/json'},
            );
          }
          return http.StreamedResponse(Stream.value(utf8.encode('{}')), 200);
        };

        recoveryRepo.configure(client: apiClient);

        await tester.pumpWidget(
          const MaterialApp(home: RecoveryRequestsScreen()),
        );
        await tester.pumpAndSettle();

        expect(find.text('Received (1)'), findsOneWidget);
        expect(find.text('Sent (0)'), findsOneWidget);
        expect(find.text('Titanium Watch'), findsOneWidget);
        expect(find.text('Danylo K.'), findsOneWidget);
      },
    );
  });
}
