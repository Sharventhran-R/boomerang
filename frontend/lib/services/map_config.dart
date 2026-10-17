import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';

class MapConfig {
  /// CartoDB Dark Matter tile layer (kept for reference or when CARTO key is provided)
  static const String darkTileUrl =
      'https://basemaps.cartocdn.com/dark_all/{z}/{x}/{y}.png';

  /// Standard OpenStreetMap raster tile layer (reliable, public, keyless)
  static const String osmTileUrl =
      'https://tile.openstreetmap.org/{z}/{x}/{y}.png';

  /// Tile attribution string
  static const String attribution = '© OpenStreetMap contributors';

  /// User agent package name compliant with tile usage policies
  static const String userAgent = 'com.boomerang.getme';

  /// Default initial map center viewport (Kyiv center: 50.4501, 30.5234)
  /// Used solely as camera orientation when no user or report location is selected
  static const LatLng defaultViewportCenter = LatLng(50.4501, 30.5234);

  /// Default zoom levels
  static const double defaultZoom = 13.0;
  static const double minZoom = 3.0;
  static const double maxZoom = 18.0;

  /// Supported search radius options in kilometers (Max 5.0 km per backend constraint)
  static const List<double> supportedRadiiKm = [0.5, 1.0, 2.0, 5.0];
  static const double defaultRadiusKm = 5.0;

  /// Default tile URL: uses OpenStreetMap by default to avoid "API KEY REQUIRED" watermark,
  /// with support for custom MAP_TILE_URL or CARTO_API_KEY if configured.
  static String get tileUrl {
    const fromEnv = String.fromEnvironment('MAP_TILE_URL');
    if (fromEnv.isNotEmpty) return fromEnv;
    const cartoKey = String.fromEnvironment('CARTO_API_KEY');
    if (cartoKey.isNotEmpty) {
      return 'https://basemaps.cartocdn.com/rastertiles/dark_all/{z}/{x}/{y}.png?key=$cartoKey';
    }
    return osmTileUrl;
  }

  /// Monochromatic dark tile builder: inverts raster tiles to dark theme
  static Widget darkTileBuilder(
    BuildContext context,
    Widget tileWidget,
    TileImage tile,
  ) {
    return ColorFiltered(
      colorFilter: const ColorFilter.matrix([
        -0.2126, -0.7152, -0.0722, 0, 255, // Invert luminance to dark
        -0.2126, -0.7152, -0.0722, 0, 255,
        -0.2126, -0.7152, -0.0722, 0, 255,
        0, 0, 0, 1, 0,
      ]),
      child: tileWidget,
    );
  }
}
