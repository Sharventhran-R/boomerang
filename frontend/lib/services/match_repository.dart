import 'package:flutter/foundation.dart';
import '../models/match_model.dart';
import 'api_client.dart';
import 'auth_service.dart';

class MatchRepository extends ChangeNotifier {
  static MatchRepository _instance = MatchRepository._internal();
  factory MatchRepository({ApiClient? client}) {
    if (client != null) {
      return MatchRepository._internal(client: client);
    }
    return _instance;
  }
  static MatchRepository get instance => _instance;

  static void setInstanceForTesting(MatchRepository repository) {
    _instance = repository;
  }

  ApiClient? _apiClient;
  bool _isMockMode = false;
  final Map<String, List<MatchModel>> _matchesByReportId = {};
  final Map<String, MatchDetailModel> _cachedMatchDetails = {};

  MatchRepository._internal({ApiClient? client}) : _apiClient = client;

  ApiClient get apiClient => _apiClient ?? AuthService.instance.apiClient;
  bool get isMockMode => _isMockMode;

  void configure({ApiClient? client, bool isMockMode = false}) {
    if (client != null) _apiClient = client;
    _isMockMode = isMockMode;
    _matchesByReportId.clear();
    _cachedMatchDetails.clear();
  }

  List<MatchModel>? getCachedMatchesForReport(String reportId) {
    return _matchesByReportId[reportId];
  }

  Future<List<MatchModel>> fetchMatchesForReport(
    String reportId, {
    String? classification,
    int page = 1,
    int pageSize = 20,
  }) async {
    if (_isMockMode) {
      return _matchesByReportId[reportId] ?? const [];
    }

    try {
      final queryParams = <String, dynamic>{
        'page': page,
        'page_size': pageSize,
      };
      if (classification != null && classification.isNotEmpty) {
        queryParams['classification'] = classification;
      }

      final response = await apiClient.get(
        '/api/v1/reports/$reportId/matches',
        queryParams: queryParams,
      );

      final data = response as Map<String, dynamic>;
      final items = <MatchModel>[];
      if (data['items'] is List) {
        for (final item in data['items'] as List) {
          if (item is Map<String, dynamic>) {
            items.add(MatchModel.fromJson(item));
          }
        }
      }

      _matchesByReportId[reportId] = items;
      notifyListeners();
      return items;
    } catch (e) {
      if (_matchesByReportId.containsKey(reportId)) {
        return _matchesByReportId[reportId]!;
      }
      rethrow;
    }
  }

  Future<MatchDetailModel> fetchMatchDetail(String matchId) async {
    if (_isMockMode && _cachedMatchDetails.containsKey(matchId)) {
      return _cachedMatchDetails[matchId]!;
    }

    final response = await apiClient.get('/api/v1/matches/$matchId');
    final detail = MatchDetailModel.fromJson(response as Map<String, dynamic>);
    _cachedMatchDetails[matchId] = detail;
    notifyListeners();
    return detail;
  }

  void setMockMatches(String reportId, List<MatchModel> matches) {
    _matchesByReportId[reportId] = matches;
    notifyListeners();
  }

  void setMockMatchDetail(String matchId, MatchDetailModel detail) {
    _cachedMatchDetails[matchId] = detail;
    notifyListeners();
  }
}

