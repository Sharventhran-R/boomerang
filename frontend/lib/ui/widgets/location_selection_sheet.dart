import 'dart:async';
import 'package:flutter/material.dart';
import '../../services/geocoding_service.dart';
import '../../services/location_service.dart';
import '../../theme.dart';
import 'app_toast.dart';

class LocationSelectionSheet extends StatefulWidget {
  final VoidCallback? onPickOnMap;
  final VoidCallback? onLocationChanged;

  const LocationSelectionSheet({
    super.key,
    this.onPickOnMap,
    this.onLocationChanged,
  });

  static Future<void> show(
    BuildContext context, {
    VoidCallback? onPickOnMap,
    VoidCallback? onLocationChanged,
  }) {
    return showModalBottomSheet(
      context: context,
      isScrollControlled: true,
      backgroundColor: AppTheme.card,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
        side: BorderSide(color: AppTheme.borderSubtle),
      ),
      builder: (_) => LocationSelectionSheet(
        onPickOnMap: onPickOnMap,
        onLocationChanged: onLocationChanged,
      ),
    );
  }

  @override
  State<LocationSelectionSheet> createState() => _LocationSelectionSheetState();
}

class _LocationSelectionSheetState extends State<LocationSelectionSheet> {
  final TextEditingController _searchController = TextEditingController();
  Timer? _debounceTimer;
  bool _isSearching = false;
  bool _isLocating = false;
  String? _gpsError;
  List<PlaceSearchResult> _searchResults = [];
  bool _hasSearched = false;

  @override
  void initState() {
    super.initState();
    LocationService.instance.addListener(_onLocationServiceChanged);
  }

  @override
  void dispose() {
    LocationService.instance.removeListener(_onLocationServiceChanged);
    _searchController.dispose();
    _debounceTimer?.cancel();
    super.dispose();
  }

  void _onLocationServiceChanged() {
    if (mounted) setState(() {});
  }

  void _onSearchQueryChanged(String query) {
    _debounceTimer?.cancel();
    final trimmed = query.trim();
    if (trimmed.length < 2) {
      setState(() {
        _isSearching = false;
        _searchResults = [];
        _hasSearched = false;
      });
      return;
    }

    setState(() {
      _isSearching = true;
    });

    _debounceTimer = Timer(const Duration(milliseconds: 400), () async {
      try {
        final results = await GeocodingService.instance.searchPlaces(trimmed);
        if (!mounted) return;
        setState(() {
          _searchResults = results;
          _isSearching = false;
          _hasSearched = true;
        });
      } catch (_) {
        if (!mounted) return;
        setState(() {
          _searchResults = [];
          _isSearching = false;
          _hasSearched = true;
        });
      }
    });
  }

  Future<void> _handleUseGps() async {
    setState(() {
      _isLocating = true;
      _gpsError = null;
    });

    try {
      final loc = await LocationService.instance.getCurrentPosition();
      if (!mounted) return;
      if (loc != null) {
        widget.onLocationChanged?.call();
        Navigator.pop(context);
        AppToast.success(
          context,
          message: 'Position updated using device GPS.',
          duration: const Duration(seconds: 2),
        );
      } else {
        setState(() {
          _gpsError =
              LocationService.instance.errorMessage ??
              'Unable to retrieve GPS coordinates. Permission may be denied or disabled.';
        });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _gpsError = 'Location error: $e';
      });
    } finally {
      if (mounted) {
        setState(() => _isLocating = false);
      }
    }
  }

  void _handleSelectPlace(PlaceSearchResult place) {
    LocationService.instance.setManualLocation(
      latitude: place.latitude,
      longitude: place.longitude,
      label: place.shortName.isNotEmpty ? place.shortName : place.displayName,
    );
    widget.onLocationChanged?.call();
    Navigator.pop(context);
    AppToast.info(
      context,
      message: 'Search anchor set to ${place.shortName}.',
      duration: const Duration(seconds: 2),
    );
  }

  void _handleClearLocation() {
    LocationService.instance.clearLocation();
    widget.onLocationChanged?.call();
    AppToast.info(
      context,
      message: 'Search anchor cleared.',
      duration: const Duration(seconds: 2),
    );
  }

  @override
  Widget build(BuildContext context) {
    final currentLoc = LocationService.instance.currentLocation;
    final bottomInset = MediaQuery.of(context).viewInsets.bottom;

    return Padding(
      padding: EdgeInsets.only(bottom: bottomInset),
      child: SafeArea(
        child: ConstrainedBox(
          constraints: BoxConstraints(
            maxHeight: MediaQuery.of(context).size.height * 0.85,
          ),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Header
              Padding(
                padding: const EdgeInsets.fromLTRB(20, 16, 12, 12),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text(
                      'Select Location Anchor',
                      style: TextStyle(
                        fontFamily: 'Hanken Grotesk',
                        fontSize: 16,
                        fontWeight: FontWeight.bold,
                        color: AppTheme.primaryText,
                      ),
                    ),
                    IconButton(
                      icon: const Icon(
                        Icons.close,
                        size: 20,
                        color: AppTheme.secondaryText,
                      ),
                      tooltip: 'Close',
                      onPressed: () => Navigator.pop(context),
                    ),
                  ],
                ),
              ),
              const Divider(color: AppTheme.borderSubtle, height: 1),

              // Active Location Indicator Card (if set)
              if (currentLoc != null)
                Padding(
                  padding: const EdgeInsets.fromLTRB(16, 12, 16, 4),
                  child: Container(
                    padding: const EdgeInsets.all(12),
                    decoration: BoxDecoration(
                      color: AppTheme.surface,
                      borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                      border: Border.all(color: AppTheme.borderSubtle),
                    ),
                    child: Row(
                      children: [
                        Icon(
                          currentLoc.isManual
                              ? Icons.pin_drop_outlined
                              : Icons.my_location,
                          size: 18,
                          color: AppTheme.primaryText,
                        ),
                        const SizedBox(width: 10),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                currentLoc.label ??
                                    (currentLoc.isManual
                                        ? 'Manual Selection'
                                        : 'Current GPS Position'),
                                style: const TextStyle(
                                  fontSize: 13,
                                  fontWeight: FontWeight.bold,
                                  color: AppTheme.primaryText,
                                ),
                                maxLines: 1,
                                overflow: TextOverflow.ellipsis,
                              ),
                              const SizedBox(height: 2),
                              Text(
                                '${currentLoc.latitude.toStringAsFixed(4)}, ${currentLoc.longitude.toStringAsFixed(4)} · Active 5.0 km radius',
                                style: const TextStyle(
                                  fontSize: 11,
                                  color: AppTheme.secondaryText,
                                ),
                              ),
                            ],
                          ),
                        ),
                        TextButton(
                          onPressed: _handleClearLocation,
                          child: const Text(
                            'Clear',
                            style: TextStyle(
                              color: AppTheme.secondaryText,
                              fontSize: 12,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                ),

              // Search Bar
              Padding(
                padding: const EdgeInsets.fromLTRB(16, 12, 16, 8),
                child: TextField(
                  controller: _searchController,
                  onChanged: _onSearchQueryChanged,
                  style: const TextStyle(
                    color: AppTheme.primaryText,
                    fontSize: 13,
                  ),
                  decoration: InputDecoration(
                    prefixIcon: const Icon(
                      Icons.search,
                      size: 18,
                      color: AppTheme.secondaryText,
                    ),
                    hintText: 'Search city, district, or address...',
                    hintStyle: const TextStyle(
                      color: AppTheme.mutedText,
                      fontSize: 13,
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
                      borderSide: const BorderSide(
                        color: AppTheme.borderSubtle,
                      ),
                    ),
                    enabledBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                      borderSide: const BorderSide(
                        color: AppTheme.borderSubtle,
                      ),
                    ),
                    focusedBorder: OutlineInputBorder(
                      borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                      borderSide: const BorderSide(
                        color: AppTheme.actionPrimary,
                      ),
                    ),
                  ),
                ),
              ),

              // Search Results or Action Buttons
              Expanded(
                child: _isSearching
                    ? const Center(
                        child: Padding(
                          padding: EdgeInsets.all(24),
                          child: CircularProgressIndicator(
                            strokeWidth: 2,
                            color: AppTheme.actionPrimary,
                          ),
                        ),
                      )
                    : _hasSearched
                    ? _searchResults.isEmpty
                          ? Center(
                              child: Padding(
                                padding: const EdgeInsets.all(24),
                                child: Text(
                                  'No places found matching "${_searchController.text.trim()}".\nTry a broader city or district name.',
                                  textAlign: TextAlign.center,
                                  style: const TextStyle(
                                    color: AppTheme.secondaryText,
                                    fontSize: 12,
                                  ),
                                ),
                              ),
                            )
                          : ListView.separated(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 16,
                                vertical: 6,
                              ),
                              itemCount: _searchResults.length,
                              separatorBuilder: (_, _) => const Divider(
                                color: AppTheme.borderSubtle,
                                height: 1,
                              ),
                              itemBuilder: (context, index) {
                                final place = _searchResults[index];
                                return ListTile(
                                  contentPadding: const EdgeInsets.symmetric(
                                    horizontal: 8,
                                    vertical: 2,
                                  ),
                                  leading: const Icon(
                                    Icons.location_on_outlined,
                                    size: 20,
                                    color: AppTheme.primaryText,
                                  ),
                                  title: Text(
                                    place.shortName,
                                    style: const TextStyle(
                                      color: AppTheme.primaryText,
                                      fontSize: 13,
                                      fontWeight: FontWeight.w600,
                                    ),
                                  ),
                                  subtitle: Text(
                                    place.displayName,
                                    style: const TextStyle(
                                      color: AppTheme.secondaryText,
                                      fontSize: 11,
                                    ),
                                    maxLines: 2,
                                    overflow: TextOverflow.ellipsis,
                                  ),
                                  onTap: () => _handleSelectPlace(place),
                                );
                              },
                            )
                    : ListView(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 16,
                          vertical: 6,
                        ),
                        children: [
                          // GPS Action Tile
                          ListTile(
                            contentPadding: const EdgeInsets.symmetric(
                              horizontal: 8,
                              vertical: 2,
                            ),
                            leading: _isLocating
                                ? const SizedBox(
                                    width: 20,
                                    height: 20,
                                    child: CircularProgressIndicator(
                                      strokeWidth: 2,
                                      color: AppTheme.actionPrimary,
                                    ),
                                  )
                                : const Icon(
                                    Icons.my_location,
                                    color: AppTheme.primaryText,
                                    size: 20,
                                  ),
                            title: const Text(
                              'Use My Current Location',
                              style: TextStyle(
                                color: AppTheme.primaryText,
                                fontSize: 13,
                                fontWeight: FontWeight.w600,
                              ),
                            ),
                            subtitle: const Text(
                              'Acquire device GPS coordinates',
                              style: TextStyle(
                                color: AppTheme.secondaryText,
                                fontSize: 11,
                              ),
                            ),
                            onTap: _isLocating ? null : _handleUseGps,
                          ),

                          if (_gpsError != null)
                            Padding(
                              padding: const EdgeInsets.fromLTRB(8, 0, 8, 8),
                              child: Container(
                                padding: const EdgeInsets.all(10),
                                decoration: BoxDecoration(
                                  color: AppTheme.surface,
                                  borderRadius: BorderRadius.circular(
                                    AppTheme.smallRadius,
                                  ),
                                  border: Border.all(
                                    color: AppTheme.borderSubtle,
                                  ),
                                ),
                                child: Row(
                                  crossAxisAlignment: CrossAxisAlignment.start,
                                  children: [
                                    const Icon(
                                      Icons.info_outline,
                                      size: 16,
                                      color: AppTheme.secondaryText,
                                    ),
                                    const SizedBox(width: 8),
                                    Expanded(
                                      child: Text(
                                        _gpsError!,
                                        style: const TextStyle(
                                          color: AppTheme.secondaryText,
                                          fontSize: 11,
                                          height: 1.3,
                                        ),
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),

                          const Divider(
                            color: AppTheme.borderSubtle,
                            height: 1,
                          ),

                          // Map Tap Action Tile
                          if (widget.onPickOnMap != null)
                            ListTile(
                              contentPadding: const EdgeInsets.symmetric(
                                horizontal: 8,
                                vertical: 2,
                              ),
                              leading: const Icon(
                                Icons.map_outlined,
                                color: AppTheme.primaryText,
                                size: 20,
                              ),
                              title: const Text(
                                'Select on Interactive Map',
                                style: TextStyle(
                                  color: AppTheme.primaryText,
                                  fontSize: 13,
                                  fontWeight: FontWeight.w600,
                                ),
                              ),
                              subtitle: const Text(
                                'Tap any sector on the map canvas to place anchor',
                                style: TextStyle(
                                  color: AppTheme.secondaryText,
                                  fontSize: 11,
                                ),
                              ),
                              onTap: () {
                                Navigator.pop(context);
                                widget.onPickOnMap?.call();
                              },
                            ),
                        ],
                      ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
