import 'package:flutter/foundation.dart';
import '../models/report_model.dart';
import '../ui/widgets/status_label.dart';
import 'api_client.dart';
import 'auth_service.dart';
import 'location_service.dart';

class ReportRepository extends ChangeNotifier {
  static ReportRepository _instance = ReportRepository._internal();
  factory ReportRepository({ApiClient? apiClient, AuthService? authService}) {
    if (apiClient != null || authService != null) {
      return ReportRepository._internal(apiClient, authService);
    }
    return _instance;
  }
  static ReportRepository get instance => _instance;

  static void setInstanceForTesting(ReportRepository repo) {
    _instance = repo;
  }

  ApiClient? _apiClient;
  AuthService? _authService;

  final List<ReportModel> _reports = [];
  final List<ReportModel> _userCreatedReports = [];
  final Map<String, ReportModel> _cachedReportsById = {};

  int _localIdSequence = 100;
  int _requestSequence = 0;
  bool _isLoading = false;
  String? _errorMessage;
  bool _hasLoaded = false;
  bool _useMockMode = false;

  ReportRepository._internal([this._apiClient, this._authService]) {
    if (_apiClient != null || _authService != null) {
      _useMockMode = false;
      _hasLoaded = false;
    } else {
      resetToDefault();
    }
  }

  ApiClient get apiClient => _apiClient ?? AuthService.instance.apiClient;
  AuthService get authService => _authService ?? AuthService.instance;

  void configure({ApiClient? client, AuthService? auth}) {
    if (client != null) _apiClient = client;
    if (auth != null) _authService = auth;
    _useMockMode = false;
    _hasLoaded = false;
    _requestSequence++;
    _reports.clear();
    _userCreatedReports.clear();
    _cachedReportsById.clear();
  }

  List<ReportModel> get reports => List.unmodifiable(_reports);

  List<ReportModel> get userReports {
    final currentUserId = authService.currentUser?.id;
    final Map<String, ReportModel> userMap = {};

    for (final r in _userCreatedReports) {
      if (_useMockMode && r.isUserReport) {
        userMap[r.id] = r;
      } else if (currentUserId != null && r.createdByUserId == currentUserId) {
        userMap[r.id] = r;
      } else if (r.isUserReport) {
        userMap[r.id] = r;
      }
    }

    for (final r in _reports) {
      if (_useMockMode && r.isUserReport) {
        userMap[r.id] = r;
      } else if (currentUserId != null && r.createdByUserId == currentUserId) {
        userMap[r.id] = r;
      }
    }

    final list = userMap.values.toList();
    list.sort((a, b) => b.dateTime.compareTo(a.dateTime));
    return List.unmodifiable(list);
  }

  bool get isLoading => _isLoading;
  String? get errorMessage => _errorMessage;
  bool get hasLoaded => _hasLoaded;
  bool get isMockMode => _useMockMode;

  double? _searchLatitude;
  double? _searchLongitude;
  double? _searchRadiusKm;

  double? get searchLatitude => _searchLatitude;
  double? get searchLongitude => _searchLongitude;
  double? get searchRadiusKm => _searchRadiusKm;

  int _total = 0;
  int _page = 1;
  int _pageSize = 50;
  int _totalPages = 0;

  int get totalReports => _total;
  int get currentPage => _page;
  int get pageSize => _pageSize;
  int get totalPages => _totalPages;

  ReportModel? getReportById(String id) {
    if (_cachedReportsById.containsKey(id)) {
      return _cachedReportsById[id];
    }
    try {
      return _reports.firstWhere((r) => r.id == id);
    } catch (_) {
      try {
        return _userCreatedReports.firstWhere((r) => r.id == id);
      } catch (_) {
        return null;
      }
    }
  }

  /// Fetch single report details from backend by ID
  Future<ReportModel?> fetchReportById(String id) async {
    // Check local memory first
    final local = getReportById(id);
    if (_useMockMode && local != null) {
      return local;
    }

    try {
      final currentUserId = authService.currentUser?.id;
      final response = await apiClient.get('/api/v1/reports/$id');
      final fetched = ReportModel.fromBackendJson(
        response as Map<String, dynamic>,
        currentUserId: currentUserId,
      );

      _cachedReportsById[id] = fetched;
      final existingIdx = _reports.indexWhere((r) => r.id == id);
      if (existingIdx >= 0) {
        _reports[existingIdx] = fetched;
      }
      final existingUserIdx = _userCreatedReports.indexWhere((r) => r.id == id);
      if (existingUserIdx >= 0) {
        _userCreatedReports[existingUserIdx] = fetched;
      } else if (currentUserId != null &&
          fetched.createdByUserId == currentUserId) {
        _userCreatedReports.add(fetched);
      }
      notifyListeners();
      return fetched;
    } catch (e) {
      if (local != null) return local;
      rethrow;
    }
  }

  /// Load reports from backend API with optional search, category, status, and geo radius filters
  Future<void> loadReports({
    bool forceRefresh = false,
    String? category,
    String? query,
    String? statusFilter,
    double? latitude,
    double? longitude,
    double? radiusKm,
    String? sort,
    int page = 1,
    int pageSize = 50,
  }) async {
    if (_useMockMode && !forceRefresh && _reports.isNotEmpty) {
      return;
    }

    final int thisRequestId = ++_requestSequence;

    _isLoading = true;
    _errorMessage = null;
    notifyListeners();

    try {
      final currentUserId = authService.currentUser?.id;
      final queryParams = <String, dynamic>{
        'page': page,
        'page_size': pageSize,
        'sort':
            sort ??
            ((latitude != null && longitude != null && radiusKm != null)
                ? 'distance'
                : 'newest'),
      };

      if (category != null && category != 'All' && category.isNotEmpty) {
        queryParams['category'] = ReportModel.toBackendCategory(category);
      }

      if (query != null && query.trim().isNotEmpty) {
        queryParams['search'] = query.trim();
      }

      if (statusFilter == 'missing') {
        queryParams['type'] = 'MISSING';
      } else if (statusFilter == 'found') {
        queryParams['type'] = 'FOUND';
      }

      if (latitude != null && longitude != null && radiusKm != null) {
        // Backend constraint: radius_km between 0.0 and 5.0, at most 1 decimal place
        final clampedRadius = radiusKm.clamp(0.1, 5.0);
        queryParams['latitude'] = latitude;
        queryParams['longitude'] = longitude;
        queryParams['radius_km'] = double.parse(
          clampedRadius.toStringAsFixed(1),
        );
        _searchLatitude = latitude;
        _searchLongitude = longitude;
        _searchRadiusKm = clampedRadius;
      } else {
        _searchLatitude = null;
        _searchLongitude = null;
        _searchRadiusKm = null;
      }

      final response = await apiClient.get(
        '/api/v1/reports',
        queryParams: queryParams,
        authenticated: authService.isAuthenticated,
      );

      // Discard stale responses from previous anchor or query
      if (thisRequestId != _requestSequence) {
        return;
      }

      if (response is Map<String, dynamic> && response['items'] is List) {
        _total = response['total'] as int? ?? 0;
        _page = response['page'] as int? ?? 1;
        _pageSize = response['page_size'] as int? ?? 50;
        _totalPages = response['total_pages'] as int? ?? 0;

        final items = (response['items'] as List)
            .map(
              (item) => ReportModel.fromBackendJson(
                item as Map<String, dynamic>,
                currentUserId: currentUserId,
              ),
            )
            .toList();

        _reports.clear();
        _reports.addAll(items);
        _hasLoaded = true;
        _useMockMode = false;
      }
    } catch (e) {
      if (thisRequestId != _requestSequence) {
        return;
      }
      _errorMessage = e is ApiException ? e.message : e.toString();
      _reports.clear();
      _total = 0;
    } finally {
      if (thisRequestId == _requestSequence) {
        _isLoading = false;
        notifyListeners();
      }
    }
  }

  List<ReportModel> searchAndFilter({
    String category = 'All',
    String query = '',
    String statusFilter = 'all',
  }) {
    return _reports.where((r) {
      if (category != 'All' &&
          !r.category.toLowerCase().contains(category.toLowerCase())) {
        return false;
      }

      if (statusFilter == 'missing' && r.status != ReportStatus.missing) {
        return false;
      }
      if (statusFilter == 'found' && r.status != ReportStatus.found) {
        return false;
      }

      if (query.isNotEmpty) {
        final q = query.toLowerCase();
        final matchesTitle = r.title.toLowerCase().contains(q);
        final matchesDesc = r.description.toLowerCase().contains(q);
        final matchesCategory = r.category.toLowerCase().contains(q);
        final matchesLocation = r.locationDescription.toLowerCase().contains(q);
        if (!matchesTitle &&
            !matchesDesc &&
            !matchesCategory &&
            !matchesLocation) {
          return false;
        }
      }

      return true;
    }).toList();
  }

  /// Creates a new report and uploads optional images.
  /// Enforces:
  /// - Only MISSING reports may offer a reward (FOUND must be null).
  /// - Reward must be non-negative.
  /// - Coordinates (latitude and longitude) sent to backend.
  /// - Images sequenced: Report created first, then images uploaded via multipart.
  Future<ReportModel> createReport({
    required String title,
    required String category,
    required String description,
    required String locationDescription,
    required DateTime dateTime,
    required ReportStatus status,
    String? reward,
    double? latitude,
    double? longitude,
    List<String> photos = const [],
    List<List<int>>? photoBytesList,
  }) async {
    if (reward != null && reward.trim().startsWith('-')) {
      throw ArgumentError('Reward cannot be negative.');
    }

    // Enforce reward rule: FOUND reports cannot have a reward
    final effectiveReward =
        (status == ReportStatus.missing &&
            reward != null &&
            reward.trim().isNotEmpty)
        ? (reward.trim().startsWith('\$') || reward.trim().startsWith('§')
              ? reward.trim()
              : '\$${reward.trim()}')
        : null;

    final lat = latitude ?? 0.0;
    final lon = longitude ?? 0.0;

    // Determine if we should submit to live backend API
    final isLiveAuth = authService.isAuthenticated || !_useMockMode;

    if (isLiveAuth) {
      final currentUserId = authService.currentUser?.id;
      final backendCat = ReportModel.toBackendCategory(category);

      double? parsedReward;
      if (status == ReportStatus.missing &&
          reward != null &&
          reward.trim().isNotEmpty) {
        final cleanNum = reward.replaceAll(RegExp(r'[^\d.]'), '');
        parsedReward = double.tryParse(cleanNum);
      }

      final requestBody = <String, dynamic>{
        'type': status == ReportStatus.missing ? 'MISSING' : 'FOUND',
        'title': title.trim(),
        'description': description.trim(),
        'category': backendCat,
        'latitude': lat,
        'longitude': lon,
        'event_time': dateTime.toIso8601String(),
      };
      if (parsedReward != null) {
        requestBody['reward_amount'] = parsedReward;
      }

      final response = await apiClient.post(
        '/api/v1/reports',
        body: requestBody,
        authenticated: true,
      );

      final createdResponse = response as Map<String, dynamic>;
      final reportId = createdResponse['id'] as String;

      // Handle optional image uploads if bytes provided
      final uploadErrors = <String>[];
      if (photoBytesList != null && photoBytesList.isNotEmpty) {
        for (int i = 0; i < photoBytesList.length; i++) {
          try {
            await apiClient.uploadMultipart(
              '/api/v1/reports/$reportId/images',
              fieldName: 'file',
              fileBytes: photoBytesList[i],
              filename: 'report_img_${i + 1}.jpg',
              contentType: 'image/jpeg',
              authenticated: true,
            );
          } catch (e) {
            uploadErrors.add('Image ${i + 1} failed: $e');
          }
        }
      }

      ReportModel finalReport;
      try {
        final refreshed = await apiClient.get(
          '/api/v1/reports/$reportId',
          authenticated: true,
        );
        finalReport = ReportModel.fromBackendJson(
          refreshed as Map<String, dynamic>,
          currentUserId: currentUserId,
        );
      } catch (_) {
        finalReport = ReportModel.fromBackendJson(
          createdResponse,
          currentUserId: currentUserId,
        );
      }

      // Cache report and store in user created reports list
      _cachedReportsById[finalReport.id] = finalReport;
      _userCreatedReports.removeWhere((r) => r.id == finalReport.id);
      _userCreatedReports.insert(0, finalReport);

      // Do NOT unconditionally prepend to nearby reports feed!
      // Refresh nearby query using active location anchor if present
      final activeLoc = LocationService.instance.currentLocation;
      if (activeLoc != null) {
        await loadReports(
          forceRefresh: true,
          latitude: activeLoc.latitude,
          longitude: activeLoc.longitude,
          radiusKm: _searchRadiusKm ?? 5.0,
        );
      } else {
        clearGeoSearch();
      }

      if (uploadErrors.isNotEmpty) {
        throw ApiException(
          statusCode: 207,
          message:
              'Report created, but some images failed to upload: ${uploadErrors.join("; ")}',
          details: {'report': finalReport, 'errors': uploadErrors},
        );
      }

      return finalReport;
    }

    // Fallback in-memory creation for mock / test mode
    await Future.delayed(const Duration(milliseconds: 100));

    final newId = 'REP-LOC-${++_localIdSequence}';
    final newReport = ReportModel(
      id: newId,
      title: title.trim(),
      category: category.trim(),
      description: description.trim(),
      locationDescription: locationDescription.trim(),
      dateTime: dateTime,
      status: status,
      reward: effectiveReward,
      distance: '0.1 km away',
      timeAgo: 'Just now',
      photos: photos,
      isUserReport: true,
      latitude: latitude,
      longitude: longitude,
      createdByUserId: authService.currentUser?.id,
    );

    _cachedReportsById[newReport.id] = newReport;
    _userCreatedReports.removeWhere((r) => r.id == newReport.id);
    _userCreatedReports.insert(0, newReport);
    _reports.removeWhere((r) => r.id == newReport.id);
    _reports.insert(0, newReport);
    notifyListeners();
    return newReport;
  }

  void clearGeoSearch() {
    _requestSequence++;
    _searchLatitude = null;
    _searchLongitude = null;
    _searchRadiusKm = null;
    if (!_useMockMode) {
      _reports.clear();
      _total = 0;
      _page = 1;
      _totalPages = 0;
      _hasLoaded = true;
    }
    _errorMessage = null;
    _isLoading = false;
    notifyListeners();
  }

  void clearUserData() {
    _requestSequence++;
    _reports.clear();
    _userCreatedReports.clear();
    _cachedReportsById.clear();
    _hasLoaded = false;
    _errorMessage = null;
    _searchLatitude = null;
    _searchLongitude = null;
    _searchRadiusKm = null;
    _total = 0;
    _page = 1;
    _totalPages = 0;
    _isLoading = false;
    notifyListeners();
  }

  void resetToDefault() {
    _reports.clear();
    _localIdSequence = 100;
    _isLoading = false;
    _errorMessage = null;
    _hasLoaded = true;
    _useMockMode = true;
    _reports.addAll([
      ReportModel(
        id: 'REP-001',
        title: 'MacBook Pro 14',
        category: 'Electronics',
        distance: '0.4 km away',
        timeAgo: '25m ago',
        status: ReportStatus.missing,
        reward: '\$150',
        description:
            'Space Black, M2 Pro, 16GB RAM. Left in sleeve at coffee counter near the window.',
        locationDescription: 'Espresso Bar, Podil, Kyiv',
        dateTime: DateTime.now().subtract(const Duration(minutes: 25)),
        isUserReport: true,
        latitude: 50.4667,
        longitude: 30.5167,
      ),
      ReportModel(
        id: 'REP-008',
        title: 'AirPods Pro Case',
        category: 'Electronics',
        distance: '0.8 km away',
        timeAgo: '1h ago',
        status: ReportStatus.found,
        reward: null,
        description:
            'White MagSafe charging case found on metro bench near turnstile.',
        locationDescription: 'Golden Gate Metro station bench',
        dateTime: DateTime.now().subtract(const Duration(hours: 1)),
        isUserReport: false,
        latitude: 50.4488,
        longitude: 30.5133,
      ),
      ReportModel(
        id: 'REP-002',
        title: 'Leather Cardholder & Keys',
        category: 'Wallet',
        distance: '0.8 km away',
        timeAgo: '1h ago',
        status: ReportStatus.found,
        reward: null,
        description:
            'Brown leather cardholder with student ID card and brass house keys on a loop.',
        locationDescription: 'Golden Gate Metro station bench',
        dateTime: DateTime.now().subtract(const Duration(hours: 1)),
        isUserReport: false,
        latitude: 50.4488,
        longitude: 30.5133,
      ),
      ReportModel(
        id: 'REP-003',
        title: 'Golden Retriever (Max)',
        category: 'Pet',
        distance: '1.2 km away',
        timeAgo: '3h ago',
        status: ReportStatus.missing,
        reward: '\$300',
        description:
            'Wearing a green collar with contact tag. Friendly but frightened of traffic.',
        locationDescription: 'Mariinsky Park east lawn',
        dateTime: DateTime.now().subtract(const Duration(hours: 3)),
        isUserReport: false,
        latitude: 50.4474,
        longitude: 30.5376,
      ),
      ReportModel(
        id: 'REP-004',
        title: 'Biometric Passport (German)',
        category: 'Documents',
        distance: '1.5 km away',
        timeAgo: '4h ago',
        status: ReportStatus.missing,
        reward: '\$80',
        description:
            'Burgundy passport in clear plastic slip. Misplaced during transit.',
        locationDescription: 'Central Train Station, Track 4',
        dateTime: DateTime.now().subtract(const Duration(hours: 4)),
        isUserReport: false,
        latitude: 50.4404,
        longitude: 30.4894,
      ),
      ReportModel(
        id: 'REP-005',
        title: 'Timbuk2 Commuter Backpack',
        category: 'Bag',
        distance: '1.9 km away',
        timeAgo: '5h ago',
        status: ReportStatus.found,
        reward: null,
        description:
            'Grey cordura backpack with cycling lights clipped on front webbing.',
        locationDescription: 'Volodymyrska Hill bicycle rack',
        dateTime: DateTime.now().subtract(const Duration(hours: 5)),
        isUserReport: true,
        latitude: 50.4561,
        longitude: 30.5262,
      ),
      ReportModel(
        id: 'REP-006',
        title: 'Honda Smart Key Fob',
        category: 'Keys',
        distance: '2.4 km away',
        timeAgo: '6h ago',
        status: ReportStatus.found,
        reward: null,
        description:
            'Black 3-button key fob on a red lanyard with gym locker tag.',
        locationDescription: 'Tarasa Shevchenka Blvd crosswalk',
        dateTime: DateTime.now().subtract(const Duration(hours: 6)),
        isUserReport: false,
        latitude: 50.4431,
        longitude: 30.5057,
      ),
      ReportModel(
        id: 'REP-007',
        title: 'Rimowa Cabin Bag (Silver)',
        category: 'Bag',
        distance: '1.2 km away',
        timeAgo: '2h ago',
        status: ReportStatus.missing,
        reward: '\$200',
        description:
            'Classic aluminum cabin bag. Contains business materials and charging accessories.',
        locationDescription: 'Central Railway Station, Waiting Hall 2',
        dateTime: DateTime.now().subtract(const Duration(hours: 2)),
        isUserReport: true,
        latitude: 50.4404,
        longitude: 30.4894,
      ),
    ]);
    notifyListeners();
  }
}
