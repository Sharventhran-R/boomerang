import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import '../../services/geocoding_service.dart';
import '../../services/location_service.dart';
import '../../services/map_config.dart';
import '../../theme.dart';

class LocationSelectionResult {
  final double latitude;
  final double longitude;
  final String address;

  const LocationSelectionResult({
    required this.latitude,
    required this.longitude,
    required this.address,
  });

  @override
  String toString() =>
      'LocationSelectionResult($address, lat: $latitude, lon: $longitude)';
}

/// Reusable Location Selection Modal Sheet for Missing and Found report creation.
/// Supports:
/// 1. Place / address search with debounced autocomplete suggestions.
/// 2. Device GPS positioning with manual refinement.
/// 3. Manual map exploration using a movable map with a fixed center pin.
/// 4. Debounced reverse geocoding to resolve human-readable addresses.
/// 5. Strict isolation from the discovery location anchor (never modifies LocationService state).
class ReportLocationPickerSheet extends StatefulWidget {
  final double? initialLatitude;
  final double? initialLongitude;
  final String? initialAddress;
  final bool isMissing;

  const ReportLocationPickerSheet({
    super.key,
    this.initialLatitude,
    this.initialLongitude,
    this.initialAddress,
    this.isMissing = true,
  });

  static Future<LocationSelectionResult?> show(
    BuildContext context, {
    double? initialLatitude,
    double? initialLongitude,
    String? initialAddress,
    bool isMissing = true,
  }) {
    return showModalBottomSheet<LocationSelectionResult>(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppTheme.card,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
        side: BorderSide(color: AppTheme.borderSubtle),
      ),
      builder: (_) => ReportLocationPickerSheet(
        initialLatitude: initialLatitude,
        initialLongitude: initialLongitude,
        initialAddress: initialAddress,
        isMissing: isMissing,
      ),
    );
  }

  @override
  State<ReportLocationPickerSheet> createState() =>
      _ReportLocationPickerSheetState();
}

class _ReportLocationPickerSheetState extends State<ReportLocationPickerSheet> {
  final MapController _mapController = MapController();
  final TextEditingController _searchController = TextEditingController();

  late LatLng _currentCenter;
  bool _hasExplicitLocation = false;
  String _currentAddress = '';

  Timer? _searchDebounceTimer;
  Timer? _reverseGeocodeDebounceTimer;
  bool _isSearching = false;
  bool _isLocatingGps = false;
  bool _isResolvingAddress = false;
  String? _gpsErrorMessage;
  List<PlaceSearchResult> _searchResults = [];
  bool _showSuggestions = false;
  int _reverseGeocodeSeq = 0;

  @override
  void initState() {
    super.initState();
    _hasExplicitLocation = true;
    if (widget.initialLatitude != null && widget.initialLongitude != null) {
      _currentCenter = LatLng(
        widget.initialLatitude!,
        widget.initialLongitude!,
      );
      _currentAddress = widget.initialAddress?.trim().isNotEmpty == true
          ? widget.initialAddress!
          : 'Selected Location';
    } else {
      _currentCenter = MapConfig.defaultViewportCenter;
      _currentAddress = 'Selected Map Location';
      _scheduleReverseGeocode(
        _currentCenter.latitude,
        _currentCenter.longitude,
      );
    }
  }

  @override
  void dispose() {
    _searchDebounceTimer?.cancel();
    _reverseGeocodeDebounceTimer?.cancel();
    _searchController.dispose();
    super.dispose();
  }

  void _onSearchQueryChanged(String query) {
    _searchDebounceTimer?.cancel();
    final trimmed = query.trim();
    if (trimmed.length < 2) {
      setState(() {
        _isSearching = false;
        _searchResults = [];
        _showSuggestions = false;
      });
      return;
    }

    setState(() {
      _isSearching = true;
      _showSuggestions = true;
    });

    _searchDebounceTimer = Timer(const Duration(milliseconds: 350), () async {
      try {
        final results = await GeocodingService.instance.searchPlaces(trimmed);
        if (!mounted) return;
        setState(() {
          _searchResults = results;
          _isSearching = false;
          _showSuggestions = true;
        });
      } catch (_) {
        if (!mounted) return;
        setState(() {
          _searchResults = [];
          _isSearching = false;
        });
      }
    });
  }

  void _selectSearchResult(PlaceSearchResult place) {
    _searchDebounceTimer?.cancel();
    _searchController.text = place.shortName;
    final target = LatLng(place.latitude, place.longitude);

    setState(() {
      _showSuggestions = false;
      _searchResults = [];
      _currentCenter = target;
      _hasExplicitLocation = true;
      _currentAddress = place.displayName.isNotEmpty
          ? place.displayName
          : place.shortName;
    });

    try {
      _mapController.move(target, 15.0);
    } catch (_) {}
  }

  Future<void> _handleUseGps() async {
    setState(() {
      _isLocatingGps = true;
      _gpsErrorMessage = null;
      _showSuggestions = false;
    });

    try {
      final loc = await LocationService.instance.getCurrentPosition();
      if (!mounted) return;

      if (loc != null) {
        final target = LatLng(loc.latitude, loc.longitude);
        setState(() {
          _currentCenter = target;
          _hasExplicitLocation = true;
          _currentAddress = 'Acquiring address...';
          _gpsErrorMessage = null;
        });

        try {
          _mapController.move(target, 16.0);
        } catch (_) {}

        _scheduleReverseGeocode(target.latitude, target.longitude);
      } else {
        setState(() {
          _gpsErrorMessage =
              LocationService.instance.errorMessage ??
              'Unable to acquire GPS fix. You can still search or pinpoint on map.';
        });
      }
    } catch (e) {
      if (mounted) {
        setState(() {
          _gpsErrorMessage = 'GPS Error: $e';
        });
      }
    } finally {
      if (mounted) {
        setState(() => _isLocatingGps = false);
      }
    }
  }

  void _onMapPositionChanged(MapCamera camera, bool hasGesture) {
    if (!hasGesture) return;

    _currentCenter = camera.center;
    if (!_hasExplicitLocation) {
      _hasExplicitLocation = true;
    }

    if (_showSuggestions) {
      setState(() => _showSuggestions = false);
    }

    _scheduleReverseGeocode(camera.center.latitude, camera.center.longitude);
  }

  void _scheduleReverseGeocode(double lat, double lon) {
    _reverseGeocodeDebounceTimer?.cancel();
    final currentSeq = ++_reverseGeocodeSeq;

    setState(() {
      _isResolvingAddress = true;
    });

    _reverseGeocodeDebounceTimer = Timer(
      const Duration(milliseconds: 500),
      () async {
        try {
          final address = await GeocodingService.instance.reverseGeocode(
            lat,
            lon,
          );
          if (!mounted || currentSeq != _reverseGeocodeSeq) return;

          setState(() {
            _isResolvingAddress = false;
            _currentAddress =
                address ??
                'Selected location [${lat.toStringAsFixed(4)}, ${lon.toStringAsFixed(4)}]';
          });
        } catch (_) {
          if (!mounted || currentSeq != _reverseGeocodeSeq) return;
          setState(() {
            _isResolvingAddress = false;
            _currentAddress =
                'Selected location [${lat.toStringAsFixed(4)}, ${lon.toStringAsFixed(4)}]';
          });
        }
      },
    );
  }

  void _confirmSelection() {
    if (!_hasExplicitLocation) return;

    final resolvedAddress =
        _currentAddress.isNotEmpty && !_currentAddress.contains('Acquiring')
        ? _currentAddress
        : 'Selected location [${_currentCenter.latitude.toStringAsFixed(4)}, ${_currentCenter.longitude.toStringAsFixed(4)}]';

    Navigator.of(context).pop(
      LocationSelectionResult(
        latitude: _currentCenter.latitude,
        longitude: _currentCenter.longitude,
        address: resolvedAddress,
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final bottomInset = MediaQuery.of(context).viewInsets.bottom;
    final isMissing = widget.isMissing;

    return Padding(
      padding: EdgeInsets.only(bottom: bottomInset),
      child: SafeArea(
        child: SizedBox(
          height: MediaQuery.of(context).size.height * 0.88,
          child: Column(
            children: [
              // 1. Modal Header
              _buildHeader(isMissing),
              const Divider(color: AppTheme.borderSubtle, height: 1),

              // 2. Search & GPS Control Bar
              _buildSearchAndGpsBar(),

              // 3. Map Canvas with Fixed Center Pin & Overlays
              Expanded(
                child: Stack(
                  children: [
                    // FlutterMap
                    FlutterMap(
                      mapController: _mapController,
                      options: MapOptions(
                        initialCenter: _currentCenter,
                        initialZoom: _hasExplicitLocation ? 15.0 : 13.0,
                        minZoom: MapConfig.minZoom,
                        maxZoom: MapConfig.maxZoom,
                        onPositionChanged: _onMapPositionChanged,
                      ),
                      children: [
                        TileLayer(
                          urlTemplate: MapConfig.tileUrl,
                          userAgentPackageName: MapConfig.userAgent,
                          tileBuilder: MapConfig.darkTileBuilder,
                        ),
                      ],
                    ),

                    // Fixed Center Pin Overlay
                    Center(
                      child: Padding(
                        padding: const EdgeInsets.only(bottom: 24),
                        child: _buildCenterPin(),
                      ),
                    ),

                    // Floating GPS Error Banner
                    if (_gpsErrorMessage != null)
                      Positioned(
                        top: 8,
                        left: 16,
                        right: 16,
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 10,
                            vertical: 8,
                          ),
                          decoration: BoxDecoration(
                            color: AppTheme.surface.withValues(alpha: 0.95),
                            borderRadius: BorderRadius.circular(
                              AppTheme.smallRadius,
                            ),
                            border: Border.all(color: AppTheme.borderSubtle),
                          ),
                          child: Row(
                            children: [
                              const Icon(
                                Icons.info_outline,
                                size: 14,
                                color: AppTheme.secondaryText,
                              ),
                              const SizedBox(width: 6),
                              Expanded(
                                child: Text(
                                  _gpsErrorMessage!,
                                  style: const TextStyle(
                                    fontSize: 11,
                                    color: AppTheme.secondaryText,
                                  ),
                                ),
                              ),
                              InkWell(
                                onTap: () =>
                                    setState(() => _gpsErrorMessage = null),
                                child: const Icon(
                                  Icons.close,
                                  size: 14,
                                  color: AppTheme.secondaryText,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ),

                    // Autocomplete Search Suggestions Dropdown Overlay
                    if (_showSuggestions)
                      Positioned(
                        top: 4,
                        left: 16,
                        right: 16,
                        child: _buildSuggestionsDropdown(),
                      ),

                    // Floating Recenter / Zoom Controls
                    Positioned(
                      right: 12,
                      bottom: 12,
                      child: Column(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          _buildMapIconButton(
                            icon: Icons.add,
                            tooltip: 'Zoom In',
                            onTap: () {
                              try {
                                final currentZoom = _mapController.camera.zoom;
                                _mapController.move(
                                  _currentCenter,
                                  (currentZoom + 1).clamp(
                                    MapConfig.minZoom,
                                    MapConfig.maxZoom,
                                  ),
                                );
                              } catch (_) {}
                            },
                          ),
                          const SizedBox(height: 6),
                          _buildMapIconButton(
                            icon: Icons.remove,
                            tooltip: 'Zoom Out',
                            onTap: () {
                              try {
                                final currentZoom = _mapController.camera.zoom;
                                _mapController.move(
                                  _currentCenter,
                                  (currentZoom - 1).clamp(
                                    MapConfig.minZoom,
                                    MapConfig.maxZoom,
                                  ),
                                );
                              } catch (_) {}
                            },
                          ),
                        ],
                      ),
                    ),
                  ],
                ),
              ),

              // 4. Bottom Confirmation Panel
              _buildConfirmationPanel(isMissing),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildHeader(bool isMissing) {
    return Padding(
      padding: const EdgeInsets.fromLTRB(16, 12, 8, 12),
      child: Row(
        mainAxisAlignment: MainAxisAlignment.spaceBetween,
        children: [
          Expanded(
            child: Row(
              children: [
                Container(
                  padding: const EdgeInsets.all(5),
                  decoration: BoxDecoration(
                    color: AppTheme.surface,
                    borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                    border: Border.all(color: AppTheme.borderSubtle),
                  ),
                  child: const Icon(
                    Icons.pin_drop_outlined,
                    size: 16,
                    color: AppTheme.primaryText,
                  ),
                ),
                const SizedBox(width: 8),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Text(
                        'Select Location on Map',
                        style: TextStyle(
                          fontFamily: 'Hanken Grotesk',
                          fontSize: 15,
                          fontWeight: FontWeight.bold,
                          color: AppTheme.primaryText,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      Text(
                        isMissing
                            ? 'Pinpoint where item was lost'
                            : 'Pinpoint where item was found',
                        style: const TextStyle(
                          fontSize: 11,
                          color: AppTheme.secondaryText,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          IconButton(
            icon: const Icon(Icons.close, size: 20),
            color: AppTheme.secondaryText,
            tooltip: 'Cancel',
            onPressed: () => Navigator.of(context).pop(),
          ),
        ],
      ),
    );
  }

  Widget _buildSearchAndGpsBar() {
    return Container(
      padding: const EdgeInsets.fromLTRB(16, 10, 16, 10),
      color: AppTheme.card,
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Search input
          TextField(
            controller: _searchController,
            onChanged: _onSearchQueryChanged,
            style: const TextStyle(color: AppTheme.primaryText, fontSize: 13),
            decoration: InputDecoration(
              prefixIcon: const Icon(
                Icons.search,
                size: 18,
                color: AppTheme.secondaryText,
              ),
              hintText: 'Search city, street, landmark, or address...',
              hintStyle: const TextStyle(
                color: AppTheme.mutedText,
                fontSize: 12.5,
              ),
              suffixIcon: _searchController.text.isNotEmpty
                  ? IconButton(
                      icon: const Icon(Icons.clear, size: 16),
                      color: AppTheme.secondaryText,
                      onPressed: () {
                        _searchController.clear();
                        _onSearchQueryChanged('');
                      },
                    )
                  : null,
              filled: true,
              fillColor: AppTheme.surface,
              contentPadding: const EdgeInsets.symmetric(
                horizontal: 12,
                vertical: 10,
              ),
              border: OutlineInputBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                borderSide: const BorderSide(color: AppTheme.borderSubtle),
              ),
              enabledBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                borderSide: const BorderSide(color: AppTheme.borderSubtle),
              ),
              focusedBorder: OutlineInputBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                borderSide: const BorderSide(color: AppTheme.borderHighlight),
              ),
            ),
          ),
          const SizedBox(height: 8),

          // Action row: Use Current GPS Location
          Row(
            children: [
              Expanded(
                child: OutlinedButton.icon(
                  onPressed: _isLocatingGps ? null : _handleUseGps,
                  icon: _isLocatingGps
                      ? const SizedBox(
                          width: 14,
                          height: 14,
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: AppTheme.primaryText,
                          ),
                        )
                      : const Icon(Icons.my_location, size: 14),
                  label: Text(
                    _isLocatingGps
                        ? 'Locating device...'
                        : 'Use My Current Location',
                    style: const TextStyle(
                      fontSize: 11.5,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  style: OutlinedButton.styleFrom(
                    side: const BorderSide(color: AppTheme.borderSubtle),
                    foregroundColor: AppTheme.primaryText,
                    padding: const EdgeInsets.symmetric(vertical: 8),
                    shape: RoundedRectangleBorder(
                      borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                    ),
                  ),
                ),
              ),
            ],
          ),
        ],
      ),
    );
  }

  Widget _buildSuggestionsDropdown() {
    return Container(
      constraints: const BoxConstraints(maxHeight: 200),
      decoration: BoxDecoration(
        color: AppTheme.card,
        borderRadius: BorderRadius.circular(AppTheme.smallRadius),
        border: Border.all(color: AppTheme.borderHighlight),
        boxShadow: const [
          BoxShadow(
            color: Colors.black87,
            blurRadius: 12,
            offset: Offset(0, 4),
          ),
        ],
      ),
      child: _isSearching
          ? const Padding(
              padding: EdgeInsets.all(16),
              child: Center(
                child: SizedBox(
                  width: 20,
                  height: 20,
                  child: CircularProgressIndicator(
                    strokeWidth: 2,
                    color: AppTheme.actionPrimary,
                  ),
                ),
              ),
            )
          : _searchResults.isEmpty
          ? const Padding(
              padding: EdgeInsets.all(16),
              child: Text(
                'No matching places found. Try typing a street or landmark.',
                style: TextStyle(color: AppTheme.secondaryText, fontSize: 12),
                textAlign: TextAlign.center,
              ),
            )
          : ListView.separated(
              shrinkWrap: true,
              padding: const EdgeInsets.symmetric(vertical: 4),
              itemCount: _searchResults.length,
              separatorBuilder: (context, index) =>
                  const Divider(color: AppTheme.borderSubtle, height: 1),
              itemBuilder: (context, index) {
                final item = _searchResults[index];
                return ListTile(
                  dense: true,
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: 12,
                    vertical: 2,
                  ),
                  leading: const Icon(
                    Icons.location_on_outlined,
                    size: 18,
                    color: AppTheme.primaryText,
                  ),
                  title: Text(
                    item.shortName,
                    style: const TextStyle(
                      color: AppTheme.primaryText,
                      fontSize: 12.5,
                      fontWeight: FontWeight.w600,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  subtitle: Text(
                    item.displayName,
                    style: const TextStyle(
                      color: AppTheme.secondaryText,
                      fontSize: 10.5,
                    ),
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                  ),
                  onTap: () => _selectSearchResult(item),
                );
              },
            ),
    );
  }

  Widget _buildCenterPin() {
    return Column(
      mainAxisSize: MainAxisSize.min,
      children: [
        Container(
          width: 38,
          height: 38,
          decoration: BoxDecoration(
            shape: BoxShape.circle,
            color: const Color(0xFF080808),
            border: Border.all(color: const Color(0xFFFFFFFF), width: 2),
            boxShadow: const [
              BoxShadow(
                color: Colors.black87,
                blurRadius: 10,
                offset: Offset(0, 4),
              ),
            ],
          ),
          child: const Center(
            child: Icon(Icons.location_on, size: 20, color: Colors.white),
          ),
        ),
        Container(
          width: 4,
          height: 12,
          decoration: const BoxDecoration(
            color: Colors.white,
            borderRadius: BorderRadius.vertical(bottom: Radius.circular(2)),
          ),
        ),
        Container(
          width: 8,
          height: 3,
          decoration: BoxDecoration(
            color: Colors.black54,
            borderRadius: BorderRadius.circular(4),
          ),
        ),
      ],
    );
  }

  Widget _buildMapIconButton({
    required IconData icon,
    required String tooltip,
    required VoidCallback onTap,
  }) {
    return Tooltip(
      message: tooltip,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppTheme.smallRadius),
        child: Container(
          width: 36,
          height: 36,
          decoration: BoxDecoration(
            color: AppTheme.card.withValues(alpha: 0.95),
            borderRadius: BorderRadius.circular(AppTheme.smallRadius),
            border: Border.all(color: AppTheme.borderSubtle),
            boxShadow: const [
              BoxShadow(
                color: Colors.black54,
                blurRadius: 6,
                offset: Offset(0, 2),
              ),
            ],
          ),
          child: Icon(icon, size: 18, color: AppTheme.primaryText),
        ),
      ),
    );
  }

  Widget _buildConfirmationPanel(bool isMissing) {
    return Container(
      padding: const EdgeInsets.all(16),
      decoration: const BoxDecoration(
        color: AppTheme.card,
        border: Border(top: BorderSide(color: AppTheme.borderSubtle)),
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.stretch,
        children: [
          // Address & Coordinates Preview
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                margin: const EdgeInsets.only(top: 2),
                padding: const EdgeInsets.all(6),
                decoration: BoxDecoration(
                  color: AppTheme.surface,
                  borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                  border: Border.all(color: AppTheme.borderSubtle),
                ),
                child: const Icon(
                  Icons.pin_drop,
                  size: 16,
                  color: AppTheme.primaryText,
                ),
              ),
              const SizedBox(width: 10),
              Expanded(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      _hasExplicitLocation
                          ? (_currentAddress.isNotEmpty
                                ? _currentAddress
                                : 'Pinpositioned location')
                          : 'No location selected yet',
                      style: TextStyle(
                        fontFamily: 'Hanken Grotesk',
                        fontWeight: FontWeight.bold,
                        fontSize: 13,
                        color: _hasExplicitLocation
                            ? AppTheme.primaryText
                            : AppTheme.mutedText,
                      ),
                      maxLines: 2,
                      overflow: TextOverflow.ellipsis,
                    ),
                    const SizedBox(height: 3),
                    Row(
                      children: [
                        if (_isResolvingAddress) ...[
                          const SizedBox(
                            width: 10,
                            height: 10,
                            child: CircularProgressIndicator(
                              strokeWidth: 1.5,
                              color: AppTheme.secondaryText,
                            ),
                          ),
                          const SizedBox(width: 6),
                          const Expanded(
                            child: Text(
                              'Resolving address...',
                              style: TextStyle(
                                fontSize: 11,
                                color: AppTheme.secondaryText,
                              ),
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        ] else ...[
                          Expanded(
                            child: Text(
                              _hasExplicitLocation
                                  ? '${_currentCenter.latitude.toStringAsFixed(6)}, ${_currentCenter.longitude.toStringAsFixed(6)}'
                                  : 'Pan map, search, or tap GPS to select',
                              style: const TextStyle(
                                fontSize: 11,
                                color: AppTheme.secondaryText,
                              ),
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                        ],
                      ],
                    ),
                  ],
                ),
              ),
            ],
          ),
          const SizedBox(height: 14),

          // Confirm Location Button
          ElevatedButton(
            key: const Key('confirm_report_location_button'),
            onPressed: _hasExplicitLocation ? _confirmSelection : null,
            style: ElevatedButton.styleFrom(
              backgroundColor: AppTheme.actionPrimary,
              foregroundColor: AppTheme.onActionPrimary,
              disabledBackgroundColor: AppTheme.surface,
              disabledForegroundColor: AppTheme.mutedText,
              padding: const EdgeInsets.symmetric(vertical: 14),
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
              ),
            ),
            child: const Text(
              'Confirm Location',
              style: TextStyle(fontSize: 13, fontWeight: FontWeight.bold),
            ),
          ),
        ],
      ),
    );
  }
}
