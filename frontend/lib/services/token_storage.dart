import 'package:flutter/foundation.dart';
import 'package:flutter_secure_storage/flutter_secure_storage.dart';

abstract class TokenStorage {
  Future<String?> getAccessToken();
  Future<String?> getRefreshToken();
  Future<void> saveTokens({
    required String accessToken,
    required String refreshToken,
  });
  Future<void> clearTokens();
}

/// In-memory storage for testing and volatile runtime contexts.
class InMemoryTokenStorage implements TokenStorage {
  String? _accessToken;
  String? _refreshToken;

  @override
  Future<String?> getAccessToken() async => _accessToken;

  @override
  Future<String?> getRefreshToken() async => _refreshToken;

  @override
  Future<void> saveTokens({
    required String accessToken,
    required String refreshToken,
  }) async {
    _accessToken = accessToken;
    _refreshToken = refreshToken;
  }

  @override
  Future<void> clearTokens() async {
    _accessToken = null;
    _refreshToken = null;
  }
}

/// Production secure storage utilizing platform hardware keystores:
/// - Android: EncryptedSharedPreferences with Android Keystore Master Key.
/// - iOS/macOS: Keychain Services with kSecAttrAccessibleAfterFirstUnlock.
/// - Windows: DPAPI (Data Protection API) user credential encryption.
/// - Web: Web Crypto API / IndexedDB storage with explicit fallback.
///
/// NOTE on Web Storage Limitations:
/// Browsers lack a hardware-backed secure enclave comparable to mobile Keystore/Keychain.
/// Sensitive tokens stored on Web are subject to origin-level XSS extraction.
/// Web deployments must enforce strict Content Security Policy (CSP), short access
/// token lifespans, and HttpOnly cookie refresh strategies where possible.
class SecurePlatformTokenStorage implements TokenStorage {
  static const String _accessTokenKey = 'boomerang_access_token';
  static const String _refreshTokenKey = 'boomerang_refresh_token';

  final FlutterSecureStorage _storage;
  final InMemoryTokenStorage _fallback = InMemoryTokenStorage();
  bool _useFallback = false;

  SecurePlatformTokenStorage({FlutterSecureStorage? storage})
    : _storage =
          storage ??
          const FlutterSecureStorage(
            aOptions: AndroidOptions(),
            iOptions: IOSOptions(
              accessibility: KeychainAccessibility.first_unlock,
            ),
            mOptions: MacOsOptions(
              accessibility: KeychainAccessibility.first_unlock,
            ),
            wOptions: WindowsOptions(),
            webOptions: WebOptions(
              dbName: 'BoomerangSecureTokens',
              publicKey: 'BoomerangKeyStorage',
            ),
          );

  @override
  Future<String?> getAccessToken() async {
    if (_useFallback) return _fallback.getAccessToken();
    try {
      return await _storage.read(key: _accessTokenKey);
    } catch (e) {
      if (kDebugMode) {
        debugPrint(
          'SecurePlatformTokenStorage: Keystore read unavailable, falling back to memory ($e)',
        );
      }
      _useFallback = true;
      return _fallback.getAccessToken();
    }
  }

  @override
  Future<String?> getRefreshToken() async {
    if (_useFallback) return _fallback.getRefreshToken();
    try {
      return await _storage.read(key: _refreshTokenKey);
    } catch (e) {
      if (kDebugMode) {
        debugPrint(
          'SecurePlatformTokenStorage: Keystore read unavailable, falling back to memory ($e)',
        );
      }
      _useFallback = true;
      return _fallback.getRefreshToken();
    }
  }

  @override
  Future<void> saveTokens({
    required String accessToken,
    required String refreshToken,
  }) async {
    if (_useFallback) {
      return _fallback.saveTokens(
        accessToken: accessToken,
        refreshToken: refreshToken,
      );
    }
    try {
      await _storage.write(key: _accessTokenKey, value: accessToken);
      await _storage.write(key: _refreshTokenKey, value: refreshToken);
    } catch (e) {
      if (kDebugMode) {
        debugPrint(
          'SecurePlatformTokenStorage: Keystore write unavailable, falling back to memory ($e)',
        );
      }
      _useFallback = true;
      await _fallback.saveTokens(
        accessToken: accessToken,
        refreshToken: refreshToken,
      );
    }
  }

  @override
  Future<void> clearTokens() async {
    if (_useFallback) return _fallback.clearTokens();
    try {
      await _storage.delete(key: _accessTokenKey);
      await _storage.delete(key: _refreshTokenKey);
    } catch (e) {
      if (kDebugMode) {
        debugPrint(
          'SecurePlatformTokenStorage: Keystore delete unavailable, falling back to memory ($e)',
        );
      }
      _useFallback = true;
      await _fallback.clearTokens();
    }
  }
}
