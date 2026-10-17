import 'dart:async';
import 'dart:convert';
import 'package:http/http.dart' as http;
import 'map_config.dart';

class PlaceSearchResult {
  final String displayName;
  final String shortName;
  final double latitude;
  final double longitude;

  const PlaceSearchResult({
    required this.displayName,
    required this.shortName,
    required this.latitude,
    required this.longitude,
  });

  factory PlaceSearchResult.fromNominatimJson(Map<String, dynamic> json) {
    final displayName = json['display_name'] as String? ?? '';
    final name = json['name'] as String?;
    final address = json['address'] as Map<String, dynamic>?;

    String shortName = name ?? '';
    if (shortName.isEmpty && address != null) {
      shortName =
          (address['city'] ??
                  address['town'] ??
                  address['village'] ??
                  address['suburb'] ??
                  address['road'] ??
                  '')
              .toString();
    }
    if (shortName.isEmpty) {
      final parts = displayName.split(',');
      shortName = parts.isNotEmpty ? parts.first.trim() : displayName;
    }

    final lat = double.tryParse(json['lat']?.toString() ?? '') ?? 0.0;
    final lon = double.tryParse(json['lon']?.toString() ?? '') ?? 0.0;

    return PlaceSearchResult(
      displayName: displayName,
      shortName: shortName,
      latitude: lat,
      longitude: lon,
    );
  }

  @override
  String toString() =>
      'PlaceSearchResult($shortName, lat: $latitude, lon: $longitude)';
}

class GeocodingService {
  static GeocodingService _instance = GeocodingService._internal();
  factory GeocodingService({http.Client? client}) {
    if (client != null) {
      return GeocodingService._internal(client: client);
    }
    return _instance;
  }
  GeocodingService._internal({http.Client? client})
    : _client = client ?? http.Client();

  static GeocodingService get instance => _instance;

  static void setInstanceForTesting(GeocodingService service) {
    _instance = service;
  }

  final http.Client _client;

  /// Search places by text query using OpenStreetMap Nominatim API
  Future<List<PlaceSearchResult>> searchPlaces(
    String query, {
    Duration timeout = const Duration(seconds: 8),
  }) async {
    final trimmed = query.trim();
    if (trimmed.length < 2) {
      return [];
    }

    final uri = Uri.https('nominatim.openstreetmap.org', '/search', {
      'q': trimmed,
      'format': 'json',
      'limit': '5',
      'addressdetails': '1',
    });

    try {
      final response = await _client
          .get(
            uri,
            headers: {
              'User-Agent': MapConfig.userAgent,
              'Accept': 'application/json',
            },
          )
          .timeout(timeout);

      if (response.statusCode != 200) {
        return [];
      }

      final data = jsonDecode(utf8.decode(response.bodyBytes));
      if (data is! List) {
        return [];
      }

      return data
          .map(
            (item) => PlaceSearchResult.fromNominatimJson(
              item as Map<String, dynamic>,
            ),
          )
          .where((r) => r.latitude != 0.0 || r.longitude != 0.0)
          .toList();
    } on TimeoutException {
      return [];
    } catch (_) {
      return [];
    }
  }
}
