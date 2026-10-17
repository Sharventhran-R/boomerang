import 'package:flutter/foundation.dart';
import '../models/recovery_request_model.dart';
import 'api_client.dart';
import 'auth_service.dart';

class RecoveryRepository extends ChangeNotifier {
  static RecoveryRepository _instance = RecoveryRepository._internal();
  factory RecoveryRepository({ApiClient? client}) {
    if (client != null) {
      return RecoveryRepository._internal(client: client);
    }
    return _instance;
  }
  static RecoveryRepository get instance => _instance;

  static void setInstanceForTesting(RecoveryRepository repository) {
    _instance = repository;
  }

  ApiClient? _apiClient;
  bool _isMockMode = true;
  bool _isLoading = false;
  String? _errorMessage;

  List<RecoveryRequestModel> _receivedRequests = [];
  List<RecoveryRequestModel> _sentRequests = [];

  bool get isLoading => _isLoading;
  bool get isMockMode => _isMockMode;
  String? get errorMessage => _errorMessage;

  List<RecoveryRequestModel> get receivedRequests =>
      List.unmodifiable(_receivedRequests);
  List<RecoveryRequestModel> get sentRequests =>
      List.unmodifiable(_sentRequests);

  ApiClient get apiClient => _apiClient ?? AuthService.instance.apiClient;

  RecoveryRepository._internal({ApiClient? client}) {
    _apiClient = client;
    _populateDefaultMocks();
  }

  void configure({ApiClient? client}) {
    if (client != null) {
      _apiClient = client;
    }
    _isMockMode = false;
    _receivedRequests.clear();
    _sentRequests.clear();
  }

  void clearUserData() {
    _receivedRequests.clear();
    _sentRequests.clear();
    _errorMessage = null;
    _isLoading = false;
    notifyListeners();
  }

  void resetToMocks() {
    _isMockMode = true;
    _populateDefaultMocks();
    notifyListeners();
  }

  void _populateDefaultMocks() {
    final now = DateTime.now();
    _receivedRequests = [
      RecoveryRequestModel(
        id: '#REQ-8941',
        reportId: 'rep-8941',
        requesterId: 'user-md',
        recipientId: 'current-user',
        status: 'pending',
        message:
            '“Hi Alex, I believe I have your MacBook at Espresso Bar. Left it with manager Ivan behind the bar with the serial number verified.”',
        verificationResponse: null,
        createdAt: now.subtract(const Duration(hours: 2)),
        updatedAt: now.subtract(const Duration(hours: 2)),
        reportTitle: 'MacBook Pro 14" (Space Black)',
        reportType: 'MISSING',
        requesterName: 'Maksym D.',
        recipientName: 'Alex Morgan',
        requesterEmail: '+380 67 482 8921 (Espresso Bar counter)',
      ),
      RecoveryRequestModel(
        id: '#REQ-8902',
        reportId: 'rep-8902',
        requesterId: 'user-ov',
        recipientId: 'current-user',
        status: 'pending',
        message:
            '“Hello! That cardholder has my student ID card inside with name Olena. Can describe card contents to verify.”',
        verificationResponse: null,
        createdAt: now.subtract(const Duration(days: 1)),
        updatedAt: now.subtract(const Duration(days: 1)),
        reportTitle: 'Brown Leather Cardholder',
        reportType: 'FOUND',
        requesterName: 'Olena V.',
        recipientName: 'Alex Morgan',
        requesterEmail: 'olena.v@student.univ.kiev.ua',
      ),
    ];

    _sentRequests = [
      RecoveryRequestModel(
        id: '#REQ-8712',
        reportId: 'rep-8712',
        requesterId: 'current-user',
        recipientId: 'user-cp',
        status: 'pending',
        message:
            '“Inquiry dispatched to Central Lost Property office registry. Verification token handshake awaiting desk agent scan.”',
        verificationResponse: null,
        createdAt: now.subtract(const Duration(days: 3)),
        updatedAt: now.subtract(const Duration(days: 3)),
        reportTitle: 'Rimowa Cabin Bag (Silver)',
        reportType: 'MISSING',
        requesterName: 'Alex Morgan',
        recipientName: 'Central Station Dispatch',
        recipientEmail: 'desk4@railway.transit.kiev.ua',
      ),
    ];
  }

  Future<void> loadRequests() async {
    if (_isMockMode) {
      return;
    }

    if (_apiClient == null && !AuthService.instance.isAuthenticated) {
      _receivedRequests.clear();
      _sentRequests.clear();
      _isLoading = false;
      notifyListeners();
      return;
    }

    _isLoading = true;
    _errorMessage = null;
    notifyListeners();

    try {
      final receivedData = await apiClient.get(
        '/api/v1/recovery-requests?type=received',
        authenticated: true,
      );
      final sentData = await apiClient.get(
        '/api/v1/recovery-requests?type=sent',
        authenticated: true,
      );

      final receivedItems = (receivedData['items'] as List<dynamic>? ?? [])
          .map(
            (item) =>
                RecoveryRequestModel.fromJson(item as Map<String, dynamic>),
          )
          .toList();

      final sentItems = (sentData['items'] as List<dynamic>? ?? [])
          .map(
            (item) =>
                RecoveryRequestModel.fromJson(item as Map<String, dynamic>),
          )
          .toList();

      _receivedRequests = receivedItems;
      _sentRequests = sentItems;
      _isLoading = false;
      notifyListeners();
    } catch (e) {
      _isLoading = false;
      _errorMessage = e is ApiException ? e.message : e.toString();
      notifyListeners();
    }
  }

  Future<RecoveryRequestModel> createRecoveryRequest({
    required String reportId,
    String? message,
  }) async {
    if (_isMockMode) {
      final now = DateTime.now();
      final mock = RecoveryRequestModel(
        id: '#REQ-${now.millisecondsSinceEpoch.toString().substring(8)}',
        reportId: reportId,
        requesterId: 'current-user',
        recipientId: 'owner-id',
        status: 'pending',
        message: message,
        createdAt: now,
        updatedAt: now,
        reportTitle: 'Target Report',
        requesterName: 'Current User',
      );
      _sentRequests.insert(0, mock);
      notifyListeners();
      return mock;
    }

    final payload = <String, dynamic>{'report_id': reportId};
    if (message != null) payload['message'] = message;

    final data = await apiClient.post(
      '/api/v1/recovery-requests',
      body: payload,
      authenticated: true,
    );

    final created = RecoveryRequestModel.fromJson(data);
    _sentRequests.insert(0, created);
    notifyListeners();
    return created;
  }

  Future<RecoveryRequestModel> updateRequestStatus({
    required String requestId,
    required String status,
    String? verificationResponse,
  }) async {
    final normalizedStatus = status.toLowerCase();

    if (_isMockMode) {
      final recIndex = _receivedRequests.indexWhere((r) => r.id == requestId);
      if (recIndex != -1) {
        final updated = _receivedRequests[recIndex].copyWith(
          status: normalizedStatus,
          verificationResponse: verificationResponse,
          updatedAt: DateTime.now(),
        );
        _receivedRequests[recIndex] = updated;
        notifyListeners();
        return updated;
      }

      final sentIndex = _sentRequests.indexWhere((r) => r.id == requestId);
      if (sentIndex != -1) {
        final updated = _sentRequests[sentIndex].copyWith(
          status: normalizedStatus,
          verificationResponse: verificationResponse,
          updatedAt: DateTime.now(),
        );
        _sentRequests[sentIndex] = updated;
        notifyListeners();
        return updated;
      }

      final now = DateTime.now();
      final fallback = RecoveryRequestModel(
        id: requestId,
        reportId: 'rep-fallback',
        requesterId: 'user',
        recipientId: 'user',
        status: normalizedStatus,
        createdAt: now,
        updatedAt: now,
      );
      notifyListeners();
      return fallback;
    }

    final payload = <String, dynamic>{'status': status.toUpperCase()};
    if (verificationResponse != null) {
      payload['verification_response'] = verificationResponse;
    }

    final data = await apiClient.patch(
      '/api/v1/recovery-requests/$requestId',
      body: payload,
      authenticated: true,
    );

    final updated = RecoveryRequestModel.fromJson(data);

    final recIndex = _receivedRequests.indexWhere((r) => r.id == requestId);
    if (recIndex != -1) {
      _receivedRequests[recIndex] = updated;
    }

    final sentIndex = _sentRequests.indexWhere((r) => r.id == requestId);
    if (sentIndex != -1) {
      _sentRequests[sentIndex] = updated;
    }

    notifyListeners();
    return updated;
  }
}
