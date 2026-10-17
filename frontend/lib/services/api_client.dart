import 'dart:convert';
import 'dart:io' show Platform;
import 'package:flutter/foundation.dart';
import 'package:http/http.dart' as http;
import 'package:http_parser/http_parser.dart';

class ApiException implements Exception {
  final int statusCode;
  final String message;
  final dynamic details;

  const ApiException({
    required this.statusCode,
    required this.message,
    this.details,
  });

  @override
  String toString() => 'ApiException($statusCode): $message';

  static ApiException fromResponse(http.Response response) {
    String message = 'Request failed with status ${response.statusCode}';
    dynamic details;

    try {
      if (response.body.isNotEmpty) {
        final decoded = jsonDecode(response.body);
        if (decoded is Map<String, dynamic>) {
          details = decoded;
          if (decoded['detail'] is String) {
            message = decoded['detail'] as String;
          } else if (decoded['detail'] is List) {
            final list = decoded['detail'] as List;
            final msgs = list.map((item) {
              if (item is Map && item['msg'] != null) {
                final loc = (item['loc'] as List?)?.last?.toString() ?? '';
                return loc.isNotEmpty
                    ? '$loc: ${item['msg']}'
                    : item['msg'].toString();
              }
              return item.toString();
            }).toList();
            message = msgs.join(', ');
          }
        }
      }
    } catch (_) {
      message = response.body.isNotEmpty ? response.body : message;
    }

    return ApiException(
      statusCode: response.statusCode,
      message: message,
      details: details,
    );
  }
}

class NetworkException implements Exception {
  final String message;
  const NetworkException(this.message);

  @override
  String toString() => 'NetworkException: $message';
}

class ApiClient {
  final String baseUrl;
  final http.Client client;
  String? Function()? tokenProvider;
  Future<bool> Function()? tokenRefresher;
  VoidCallback? onSessionExpired;

  ApiClient({
    String? baseUrl,
    http.Client? client,
    this.tokenProvider,
    this.tokenRefresher,
    this.onSessionExpired,
  }) : baseUrl = baseUrl ?? resolveDefaultBaseUrl(),
       client = client ?? http.Client();

  static String resolveDefaultBaseUrl() {
    const fromEnv = String.fromEnvironment('API_BASE_URL');
    if (fromEnv.isNotEmpty) return fromEnv;
    if (!kIsWeb) {
      try {
        if (Platform.isAndroid) return 'http://10.0.2.2:8000';
      } catch (_) {}
    }
    return 'http://127.0.0.1:8000';
  }

  Uri _buildUri(String path, [Map<String, dynamic>? queryParams]) {
    final cleanBase = baseUrl.endsWith('/')
        ? baseUrl.substring(0, baseUrl.length - 1)
        : baseUrl;
    final cleanPath = path.startsWith('/') ? path : '/$path';
    final urlString = '$cleanBase$cleanPath';

    final uri = Uri.parse(urlString);
    if (queryParams != null && queryParams.isNotEmpty) {
      final sanitizedParams = <String, String>{};
      queryParams.forEach((key, value) {
        if (value != null) {
          sanitizedParams[key] = value.toString();
        }
      });
      return uri.replace(queryParameters: sanitizedParams);
    }
    return uri;
  }

  Map<String, String> _buildHeaders({
    bool authenticated = true,
    String? contentType,
  }) {
    final headers = <String, String>{'Accept': 'application/json'};
    if (contentType != null) {
      headers['Content-Type'] = contentType;
    }
    if (authenticated && tokenProvider != null) {
      final token = tokenProvider!();
      if (token != null && token.isNotEmpty) {
        headers['Authorization'] = 'Bearer $token';
      }
    }
    return headers;
  }

  Future<dynamic> get(
    String path, {
    Map<String, dynamic>? queryParams,
    bool authenticated = true,
  }) async {
    return _executeWithAuth(
      (headers) => client.get(_buildUri(path, queryParams), headers: headers),
      authenticated: authenticated,
    );
  }

  Future<dynamic> post(
    String path, {
    dynamic body,
    bool authenticated = true,
  }) async {
    return _executeWithAuth(
      (headers) => client.post(
        _buildUri(path),
        headers: headers,
        body: body != null ? jsonEncode(body) : null,
      ),
      authenticated: authenticated,
      contentType: 'application/json; charset=UTF-8',
    );
  }

  Future<dynamic> patch(
    String path, {
    dynamic body,
    bool authenticated = true,
  }) async {
    return _executeWithAuth(
      (headers) => client.patch(
        _buildUri(path),
        headers: headers,
        body: body != null ? jsonEncode(body) : null,
      ),
      authenticated: authenticated,
      contentType: 'application/json; charset=UTF-8',
    );
  }

  Future<dynamic> delete(
    String path, {
    dynamic body,
    bool authenticated = true,
  }) async {
    return _executeWithAuth(
      (headers) => client.delete(
        _buildUri(path),
        headers: headers,
        body: body != null ? jsonEncode(body) : null,
      ),
      authenticated: authenticated,
      contentType: 'application/json; charset=UTF-8',
    );
  }

  Future<dynamic> uploadMultipart(
    String path, {
    required String fieldName,
    required List<int> fileBytes,
    required String filename,
    String contentType = 'image/jpeg',
    bool authenticated = true,
  }) async {
    final uri = _buildUri(path);
    final headers = _buildHeaders(authenticated: authenticated);

    try {
      final request = http.MultipartRequest('POST', uri);
      request.headers.addAll(headers);

      final mediaType = MediaType.parse(contentType);
      final multipartFile = http.MultipartFile.fromBytes(
        fieldName,
        fileBytes,
        filename: filename,
        contentType: mediaType,
      );
      request.files.add(multipartFile);

      final streamedResponse = await client.send(request);
      final response = await http.Response.fromStream(streamedResponse);

      if (response.statusCode == 401 &&
          authenticated &&
          tokenRefresher != null) {
        final refreshed = await tokenRefresher!();
        if (refreshed) {
          final retryHeaders = _buildHeaders(authenticated: true);
          final retryRequest = http.MultipartRequest('POST', uri);
          retryRequest.headers.addAll(retryHeaders);
          retryRequest.files.add(
            http.MultipartFile.fromBytes(
              fieldName,
              fileBytes,
              filename: filename,
              contentType: mediaType,
            ),
          );
          final retryStreamed = await client.send(retryRequest);
          final retryResponse = await http.Response.fromStream(retryStreamed);
          return _handleResponse(retryResponse);
        } else {
          onSessionExpired?.call();
          throw const ApiException(
            statusCode: 401,
            message: 'Session expired. Please log in again.',
          );
        }
      }

      return _handleResponse(response);
    } on ApiException {
      rethrow;
    } catch (e) {
      throw NetworkException('Network error during upload: $e');
    }
  }

  Future<dynamic> _executeWithAuth(
    Future<http.Response> Function(Map<String, String> headers) requestFn, {
    required bool authenticated,
    String? contentType,
  }) async {
    try {
      final headers = _buildHeaders(
        authenticated: authenticated,
        contentType: contentType,
      );
      final response = await requestFn(headers);

      if (response.statusCode == 401 &&
          authenticated &&
          tokenRefresher != null) {
        final refreshed = await tokenRefresher!();
        if (refreshed) {
          final retryHeaders = _buildHeaders(
            authenticated: true,
            contentType: contentType,
          );
          final retryResponse = await requestFn(retryHeaders);
          return _handleResponse(retryResponse);
        } else {
          onSessionExpired?.call();
          throw const ApiException(
            statusCode: 401,
            message: 'Session expired. Please log in again.',
          );
        }
      }

      return _handleResponse(response);
    } on ApiException {
      rethrow;
    } catch (e) {
      throw NetworkException('Network connection error: $e');
    }
  }

  dynamic _handleResponse(http.Response response) {
    if (response.statusCode >= 200 && response.statusCode < 300) {
      if (response.statusCode == 204 || response.body.isEmpty) {
        return null;
      }
      return jsonDecode(response.body);
    }
    throw ApiException.fromResponse(response);
  }
}
