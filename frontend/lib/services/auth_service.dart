import 'package:flutter/foundation.dart';
import '../models/auth_tokens.dart';
import '../models/user_model.dart';
import 'api_client.dart';
import 'recovery_repository.dart';
import 'report_repository.dart';
import 'token_storage.dart';

class AuthService extends ChangeNotifier {
  static AuthService _instance = AuthService._internal();
  factory AuthService({ApiClient? client, TokenStorage? storage}) {
    if (client != null || storage != null) {
      return AuthService._internal(client: client, storage: storage);
    }
    return _instance;
  }
  static AuthService get instance => _instance;

  static void setInstanceForTesting(AuthService service) {
    _instance = service;
  }

  final ApiClient apiClient;
  final TokenStorage tokenStorage;

  UserModel? _currentUser;
  String? _currentAccessToken;
  bool _isInitialized = false;

  UserModel? get currentUser => _currentUser;
  bool get isAuthenticated =>
      _currentUser != null && _currentAccessToken != null;
  bool get isInitialized => _isInitialized;
  String? get currentAccessToken => _currentAccessToken;

  AuthService._internal({ApiClient? client, TokenStorage? storage})
    : tokenStorage = storage ?? SecurePlatformTokenStorage(),
      apiClient = client ?? ApiClient() {
    _setupApiClient();
  }

  void _setupApiClient() {
    apiClient.tokenProvider = () => _currentAccessToken;
    apiClient.tokenRefresher = refreshToken;
    apiClient.onSessionExpired = () {
      _clearSession();
      notifyListeners();
    };
  }

  /// Initialize and attempt session restoration from stored tokens.
  Future<void> restoreSession() async {
    try {
      final storedAccessToken = await tokenStorage.getAccessToken();
      final storedRefreshToken = await tokenStorage.getRefreshToken();

      if (storedAccessToken == null && storedRefreshToken == null) {
        _isInitialized = true;
        notifyListeners();
        return;
      }

      _currentAccessToken = storedAccessToken;

      if (_currentAccessToken != null) {
        try {
          await _fetchProfile();
          _isInitialized = true;
          notifyListeners();
          return;
        } catch (e) {
          if (e is! ApiException || e.statusCode != 401) {
            // Network error or server error, retain token for offline if needed
            _isInitialized = true;
            notifyListeners();
            return;
          }
        }
      }

      // Access token was missing or expired (401), attempt refresh
      if (storedRefreshToken != null) {
        final refreshed = await refreshToken();
        if (refreshed) {
          await _fetchProfile();
        }
      }
    } catch (_) {
      await _clearSession();
    } finally {
      _isInitialized = true;
      notifyListeners();
    }
  }

  Future<UserModel> register({
    required String name,
    required String email,
    required String password,
  }) async {
    final response = await apiClient.post(
      '/api/v1/auth/register',
      body: {
        'name': name.trim(),
        'email': email.trim().toLowerCase(),
        'password': password,
      },
      authenticated: false,
    );

    return UserModel.fromJson(response as Map<String, dynamic>);
  }

  Future<UserModel> login({
    required String email,
    required String password,
  }) async {
    final response = await apiClient.post(
      '/api/v1/auth/login',
      body: {'email': email.trim().toLowerCase(), 'password': password},
      authenticated: false,
    );

    final tokens = AuthTokens.fromJson(response as Map<String, dynamic>);
    _currentAccessToken = tokens.accessToken;
    await tokenStorage.saveTokens(
      accessToken: tokens.accessToken,
      refreshToken: tokens.refreshToken,
    );

    final user = await _fetchProfile();
    notifyListeners();
    return user;
  }

  Future<bool> refreshToken() async {
    final storedRefreshToken = await tokenStorage.getRefreshToken();
    if (storedRefreshToken == null || storedRefreshToken.isEmpty) {
      await _clearSession();
      return false;
    }

    try {
      final response = await apiClient.post(
        '/api/v1/auth/refresh',
        body: {'refresh_token': storedRefreshToken},
        authenticated: false,
      );

      final tokens = AuthTokens.fromJson(response as Map<String, dynamic>);
      _currentAccessToken = tokens.accessToken;
      await tokenStorage.saveTokens(
        accessToken: tokens.accessToken,
        refreshToken: tokens.refreshToken,
      );
      notifyListeners();
      return true;
    } catch (_) {
      await _clearSession();
      return false;
    }
  }

  Future<void> logout() async {
    final storedRefreshToken = await tokenStorage.getRefreshToken();
    if (storedRefreshToken != null && storedRefreshToken.isNotEmpty) {
      try {
        await apiClient.post(
          '/api/v1/auth/logout',
          body: {'refresh_token': storedRefreshToken},
          authenticated: false,
        );
      } catch (_) {
        // Ignore network failure during logout
      }
    }

    await _clearSession();
    ReportRepository.instance.clearUserData();
    RecoveryRepository.instance.clearUserData();
    notifyListeners();
  }

  Future<UserModel> _fetchProfile() async {
    final response = await apiClient.get(
      '/api/v1/users/me',
      authenticated: true,
    );

    final user = UserModel.fromJson(response as Map<String, dynamic>);
    _currentUser = user;
    return user;
  }

  Future<void> _clearSession() async {
    _currentUser = null;
    _currentAccessToken = null;
    await tokenStorage.clearTokens();
  }

  /// Manually set user and token for testing or explicit session setup
  void setSessionForTesting({
    required UserModel user,
    required String accessToken,
    String? refreshToken,
  }) {
    _currentUser = user;
    _currentAccessToken = accessToken;
    _isInitialized = true;
    if (refreshToken != null) {
      tokenStorage.saveTokens(
        accessToken: accessToken,
        refreshToken: refreshToken,
      );
    }
    notifyListeners();
  }
}
