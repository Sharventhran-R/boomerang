import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import '../../models/report_model.dart';
import '../../services/auth_service.dart';
import '../../services/location_service.dart';
import '../../services/map_config.dart';
import '../../services/report_repository.dart';
import '../../theme.dart';
import '../widgets/app_toast.dart';
import '../widgets/location_selection_sheet.dart';
import '../widgets/status_label.dart';
import 'profile_screen.dart';
import 'report_details_screen.dart';

class MapScreen extends StatefulWidget {
  final ValueChanged<int>? onNavigateTab;

  const MapScreen({super.key, this.onNavigateTab});

  @override
  State<MapScreen> createState() => _MapScreenState();
}

class _MapScreenState extends State<MapScreen> {
  final MapController _mapController = MapController();
  final TextEditingController _mapSearchController = TextEditingController();

  bool _isSheetExpanded = false;
  double _selectedRadiusKm = MapConfig.defaultRadiusKm;
  String _statusFilter = 'all'; // 'all', 'missing', 'found'
  ReportModel? _selectedMarkerReport;
  bool _isLocating = false;

  @override
  void initState() {
    super.initState();
    ReportRepository.instance.addListener(_onReportsChanged);
    LocationService.instance.addListener(_onLocationChanged);

    // Initial load of reports if not already loaded and anchor is present
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (!ReportRepository.instance.hasLoaded && _activeAnchor != null) {
        _loadReportsForActiveArea();
      } else if (_activeAnchor == null &&
          !ReportRepository.instance.isMockMode) {
        ReportRepository.instance.clearGeoSearch();
      }
    });
  }

  void _onReportsChanged() {
    if (mounted) setState(() {});
  }

  void _onLocationChanged() {
    if (!mounted) return;
    setState(() {});
    final anchor = _activeAnchor;
    if (anchor != null) {
      try {
        final currentZoom = _mapController.camera.zoom;
        final targetZoom = (currentZoom.isNaN || currentZoom < 10)
            ? MapConfig.defaultZoom
            : currentZoom;
        _mapController.move(anchor, targetZoom);
      } catch (_) {
        // Map controller not yet attached or rendered
      }
      _loadReportsForActiveArea();
    } else {
      if (!ReportRepository.instance.isMockMode) {
        ReportRepository.instance.clearGeoSearch();
      }
    }
  }

  @override
  void dispose() {
    ReportRepository.instance.removeListener(_onReportsChanged);
    LocationService.instance.removeListener(_onLocationChanged);
    _mapSearchController.dispose();
    super.dispose();
  }

  LatLng? get _activeAnchor {
    final loc = LocationService.instance.currentLocation;
    if (loc != null) {
      return loc.toLatLng();
    }
    return null;
  }

  String get _locationLabel {
    final loc = LocationService.instance.currentLocation;
    if (loc != null) {
      if (loc.isManual) {
        return loc.label ??
            'Anchor [${loc.latitude.toStringAsFixed(2)}, ${loc.longitude.toStringAsFixed(2)}]';
      }
      return loc.label ?? 'My GPS Location';
    }
    return 'Select Location';
  }

  Future<void> _loadReportsForActiveArea({double? radius}) async {
    final anchor = _activeAnchor;
    if (anchor == null && !ReportRepository.instance.isMockMode) {
      ReportRepository.instance.clearGeoSearch();
      return;
    }
    final effRadius = radius ?? _selectedRadiusKm;

    await ReportRepository.instance.loadReports(
      statusFilter: _statusFilter == 'all' ? null : _statusFilter,
      query: _mapSearchController.text.trim().isNotEmpty
          ? _mapSearchController.text.trim()
          : null,
      latitude: anchor?.latitude,
      longitude: anchor?.longitude,
      radiusKm: anchor != null ? effRadius : null,
    );
  }

  void _toggleSheet() {
    setState(() => _isSheetExpanded = !_isSheetExpanded);
  }

  void _navigateToProfile() {
    if (widget.onNavigateTab != null) {
      widget.onNavigateTab!(4);
    } else {
      Navigator.push(
        context,
        MaterialPageRoute(builder: (_) => const ProfileScreen()),
      );
    }
  }

  /// Request actual GPS location from device
  Future<void> _requestGpsLocation() async {
    setState(() => _isLocating = true);

    try {
      final locData = await LocationService.instance.getCurrentPosition();

      if (!mounted) return;

      if (locData != null) {
        final point = locData.toLatLng();
        try {
          _mapController.move(point, 14.0);
        } catch (_) {}

        AppToast.success(
          context,
          message: 'Position located via GPS. Updating nearby reports.',
          duration: const Duration(seconds: 2),
        );

        await _loadReportsForActiveArea();
      } else {
        _handleLocationFailure();
      }
    } finally {
      if (mounted) {
        setState(() => _isLocating = false);
      }
    }
  }

  void _handleLocationFailure() {
    final status = LocationService.instance.status;
    final message =
        LocationService.instance.errorMessage ??
        'Unable to acquire device position.';

    showModalBottomSheet(
      context: context,
      backgroundColor: AppTheme.card,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
        side: BorderSide(color: AppTheme.borderSubtle),
      ),
      builder: (ctx) {
        return SafeArea(
          child: Padding(
            padding: const EdgeInsets.all(20),
            child: Column(
              mainAxisSize: MainAxisSize.min,
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    const Icon(
                      Icons.location_off_outlined,
                      color: AppTheme.primaryText,
                      size: 20,
                    ),
                    const SizedBox(width: 10),
                    const Expanded(
                      child: Text(
                        'Location Service Notice',
                        style: TextStyle(
                          fontFamily: 'Hanken Grotesk',
                          fontSize: 16,
                          fontWeight: FontWeight.bold,
                          color: AppTheme.primaryText,
                        ),
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.close, size: 18),
                      color: AppTheme.secondaryText,
                      onPressed: () => Navigator.pop(ctx),
                    ),
                  ],
                ),
                const SizedBox(height: 12),
                Text(
                  message,
                  style: const TextStyle(
                    fontSize: 13,
                    color: AppTheme.secondaryText,
                    height: 1.4,
                  ),
                ),
                const SizedBox(height: 8),
                const Text(
                  'Boomerang allows you to tap anywhere on the map to set an exploration anchor manually without GPS permissions.',
                  style: TextStyle(
                    fontSize: 12,
                    color: AppTheme.mutedText,
                    height: 1.4,
                  ),
                ),
                const SizedBox(height: 20),
                Row(
                  children: [
                    Expanded(
                      child: OutlinedButton(
                        onPressed: () {
                          Navigator.pop(ctx);
                          AppToast.info(
                            context,
                            message:
                                'Tap anywhere on the map to place a manual search anchor.',
                            duration: const Duration(seconds: 3),
                          );
                        },
                        style: OutlinedButton.styleFrom(
                          side: const BorderSide(color: AppTheme.borderSubtle),
                          foregroundColor: AppTheme.primaryText,
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(
                              AppTheme.smallRadius,
                            ),
                          ),
                          padding: const EdgeInsets.symmetric(vertical: 12),
                        ),
                        child: const Text('Tap Map Manually'),
                      ),
                    ),
                    const SizedBox(width: 10),
                    if (status != LocationPermissionStatus.deniedForever)
                      Expanded(
                        child: ElevatedButton(
                          onPressed: () {
                            Navigator.pop(ctx);
                            _requestGpsLocation();
                          },
                          style: ElevatedButton.styleFrom(
                            backgroundColor: AppTheme.actionPrimary,
                            foregroundColor: AppTheme.onActionPrimary,
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(
                                AppTheme.smallRadius,
                              ),
                            ),
                            padding: const EdgeInsets.symmetric(vertical: 12),
                          ),
                          child: const Text('Retry GPS'),
                        ),
                      ),
                  ],
                ),
              ],
            ),
          ),
        );
      },
    );
  }

  /// User taps anywhere on the map canvas to set manual location anchor
  void _onMapTapped(LatLng point) {
    setState(() {
      _selectedMarkerReport = null;
    });

    LocationService.instance.setManualLocation(
      latitude: point.latitude,
      longitude: point.longitude,
      label:
          'Point [${point.latitude.toStringAsFixed(3)}, ${point.longitude.toStringAsFixed(3)}]',
    );

    AppToast.info(
      context,
      message:
          'Search anchor placed at [${point.latitude.toStringAsFixed(4)}, ${point.longitude.toStringAsFixed(4)}].',
      duration: const Duration(seconds: 2),
    );

    _loadReportsForActiveArea();
  }

  void _showLocationMenu() {
    LocationSelectionSheet.show(
      context,
      onPickOnMap: () {
        AppToast.info(
          context,
          message: 'Tap anywhere on the map to anchor your search radius.',
        );
      },
      onLocationChanged: () {
        _onLocationChanged();
      },
    );
  }

  void _showMapInfoDialog() {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.card,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
          side: const BorderSide(color: AppTheme.borderSubtle),
        ),
        title: const Row(
          children: [
            Icon(Icons.info_outline, color: AppTheme.primaryText, size: 20),
            SizedBox(width: 8),
            Text(
              'Map Guide & Attribution',
              style: TextStyle(
                color: AppTheme.primaryText,
                fontSize: 16,
                fontWeight: FontWeight.bold,
              ),
            ),
          ],
        ),
        content: Column(
          mainAxisSize: MainAxisSize.min,
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Text(
              '• Monochromatic Real Map: CartoDB Dark Matter tiles.',
              style: TextStyle(color: AppTheme.secondaryText, fontSize: 13),
            ),
            const SizedBox(height: 6),
            const Text(
              '• Missing Marker: Solid badge with search icon representing unrecovered items.',
              style: TextStyle(color: AppTheme.secondaryText, fontSize: 13),
            ),
            const SizedBox(height: 6),
            const Text(
              '• Found Marker: Grayscale badge with checkmark representing recovered items.',
              style: TextStyle(color: AppTheme.secondaryText, fontSize: 13),
            ),
            const SizedBox(height: 6),
            const Text(
              '• Search Radius: PostGIS geospatial queries (0.5 to 5.0 km).',
              style: TextStyle(color: AppTheme.secondaryText, fontSize: 13),
            ),
            const SizedBox(height: 10),
            const Divider(color: AppTheme.borderSubtle),
            const SizedBox(height: 6),
            Text(
              MapConfig.attribution,
              style: const TextStyle(
                color: AppTheme.mutedText,
                fontSize: 11,
                fontStyle: FontStyle.italic,
              ),
            ),
          ],
        ),
        actions: [
          ElevatedButton(
            onPressed: () => Navigator.pop(ctx),
            style: ElevatedButton.styleFrom(
              backgroundColor: AppTheme.actionPrimary,
              foregroundColor: AppTheme.onActionPrimary,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
              ),
            ),
            child: const Text('Close'),
          ),
        ],
      ),
    );
  }

  void _onRadiusSelected(double radius) {
    setState(() => _selectedRadiusKm = radius);

    if (_activeAnchor == null) {
      AppToast.info(
        context,
        message:
            'Radius set to ${radius.toStringAsFixed(1)} km. Tap map or use GPS to anchor search.',
        duration: const Duration(seconds: 3),
      );
      return;
    }

    _loadReportsForActiveArea(radius: radius);
  }

  void _onStatusFilterSelected(String status) {
    setState(() => _statusFilter = status);
    _loadReportsForActiveArea();
  }

  List<ReportModel> get _filteredReports {
    if (_activeAnchor == null && !ReportRepository.instance.isMockMode) {
      return const <ReportModel>[];
    }
    final query = _mapSearchController.text.trim().toLowerCase();
    return ReportRepository.instance.reports.where((r) {
      if (_statusFilter == 'missing' && r.status != ReportStatus.missing) {
        return false;
      }
      if (_statusFilter == 'found' && r.status != ReportStatus.found) {
        return false;
      }
      if (query.isNotEmpty) {
        final matchesTitle = r.title.toLowerCase().contains(query);
        final matchesDesc = r.description.toLowerCase().contains(query);
        final matchesCat = r.category.toLowerCase().contains(query);
        final matchesLoc = r.locationDescription.toLowerCase().contains(query);
        if (!matchesTitle && !matchesDesc && !matchesCat && !matchesLoc) {
          return false;
        }
      }
      return true;
    }).toList();
  }

  @override
  Widget build(BuildContext context) {
    final isDesktop = MediaQuery.of(context).size.width >= 840;

    if (isDesktop) {
      return _buildDesktopLayout();
    }
    return _buildMobileLayout();
  }

  Widget _buildDesktopLayout() {
    return Scaffold(
      backgroundColor: AppTheme.background,
      body: Row(
        children: [
          // Left Sidebar Control & Reports Panel (400px)
          Container(
            width: 400,
            decoration: const BoxDecoration(
              color: AppTheme.surface,
              border: Border(right: BorderSide(color: AppTheme.borderSubtle)),
            ),
            child: SafeArea(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Padding(
                    padding: const EdgeInsets.all(16),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          mainAxisAlignment: MainAxisAlignment.spaceBetween,
                          children: [
                            Row(
                              mainAxisSize: MainAxisSize.min,
                              children: [
                                Container(
                                  padding: const EdgeInsets.all(5),
                                  decoration: BoxDecoration(
                                    color: AppTheme.card,
                                    borderRadius: BorderRadius.circular(
                                      AppTheme.smallRadius,
                                    ),
                                    border: Border.all(
                                      color: AppTheme.borderSubtle,
                                    ),
                                  ),
                                  child: const Icon(
                                    Icons.map_outlined,
                                    size: 16,
                                    color: AppTheme.primaryText,
                                  ),
                                ),
                                const SizedBox(width: 8),
                                const Text(
                                  'Explore Map',
                                  style: TextStyle(
                                    fontFamily: 'Hanken Grotesk',
                                    fontWeight: FontWeight.bold,
                                    fontSize: 16,
                                  ),
                                ),
                              ],
                            ),
                            const SizedBox(width: 8),
                            Flexible(
                              child: InkWell(
                                onTap: _showLocationMenu,
                                borderRadius: BorderRadius.circular(
                                  AppTheme.smallRadius,
                                ),
                                child: Container(
                                  padding: const EdgeInsets.symmetric(
                                    horizontal: 8,
                                    vertical: 4,
                                  ),
                                  decoration: BoxDecoration(
                                    color: AppTheme.card,
                                    borderRadius: BorderRadius.circular(
                                      AppTheme.smallRadius,
                                    ),
                                    border: Border.all(
                                      color: AppTheme.borderSubtle,
                                    ),
                                  ),
                                  child: Row(
                                    mainAxisSize: MainAxisSize.min,
                                    children: [
                                      Icon(
                                        _activeAnchor != null
                                            ? Icons.location_on
                                            : Icons.location_off_outlined,
                                        size: 12,
                                        color: AppTheme.primaryText,
                                      ),
                                      const SizedBox(width: 4),
                                      Flexible(
                                        child: Text(
                                          _locationLabel,
                                          style: const TextStyle(
                                            fontSize: 11,
                                            color: AppTheme.primaryText,
                                          ),
                                          maxLines: 1,
                                          overflow: TextOverflow.ellipsis,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                              ),
                            ),
                          ],
                        ),
                        const SizedBox(height: 12),
                        _buildFloatingSearchRow(),
                        const SizedBox(height: 8),
                        _buildFilterAndRadiusRow(),
                      ],
                    ),
                  ),
                  if (ReportRepository.instance.isLoading || _isLocating)
                    const LinearProgressIndicator(
                      minHeight: 2,
                      backgroundColor: AppTheme.surface,
                      color: AppTheme.actionPrimary,
                    ),
                  const Divider(color: AppTheme.borderSubtle, height: 1),

                  // Nearby Reports Panel
                  Expanded(
                    child: Padding(
                      padding: const EdgeInsets.all(16),
                      child: _buildNearbyReportsPanel(),
                    ),
                  ),
                ],
              ),
            ),
          ),

          // Right Expanded Real Map Canvas
          Expanded(
            child: Stack(
              children: [
                _buildRealMapWidget(),

                Positioned(
                  top: 16,
                  right: 16,
                  child: Row(
                    children: [
                      _buildTopIcon(
                        Icons.info_outline,
                        tooltip: 'Map Legend & Info',
                        semanticsLabel: 'Map guide info',
                        onTap: _showMapInfoDialog,
                      ),
                      const SizedBox(width: 8),
                      _buildAvatarButton(),
                    ],
                  ),
                ),

                if (_selectedMarkerReport != null)
                  Positioned(
                    left: 20,
                    bottom: 20,
                    width: 360,
                    child: _buildSelectedMarkerPreviewCard(),
                  ),
              ],
            ),
          ),
        ],
      ),
    );
  }

  // Full-Screen Mobile Map Experience
  Widget _buildMobileLayout() {
    return Scaffold(
      backgroundColor: AppTheme.background,
      body: Stack(
        children: [
          // 1. Full-screen Real Map Canvas
          Positioned.fill(child: _buildRealMapWidget()),

          // 2. Top Header (Location Pill & Avatar)
          Positioned(
            top: MediaQuery.of(context).padding.top + 10,
            left: 16,
            right: 16,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                // Location Selector Pill
                Flexible(
                  child: Semantics(
                    button: true,
                    label: 'Map anchor: $_locationLabel. Tap to adjust',
                    child: Tooltip(
                      message: 'Location Controls',
                      child: InkWell(
                        onTap: _showLocationMenu,
                        borderRadius: BorderRadius.circular(
                          AppTheme.smallRadius,
                        ),
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 10,
                            vertical: 6,
                          ),
                          decoration: BoxDecoration(
                            color: AppTheme.card.withValues(alpha: 0.95),
                            border: Border.all(color: AppTheme.borderSubtle),
                            borderRadius: BorderRadius.circular(
                              AppTheme.smallRadius,
                            ),
                            boxShadow: const [
                              BoxShadow(
                                color: Colors.black45,
                                blurRadius: 8,
                                offset: Offset(0, 2),
                              ),
                            ],
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Icon(
                                _activeAnchor != null
                                    ? Icons.location_on
                                    : Icons.location_searching,
                                size: 14,
                                color: AppTheme.primaryText,
                              ),
                              const SizedBox(width: 5),
                              Flexible(
                                child: Text(
                                  _locationLabel,
                                  style: const TextStyle(
                                    fontSize: 12,
                                    fontWeight: FontWeight.bold,
                                    color: AppTheme.primaryText,
                                  ),
                                  maxLines: 1,
                                  overflow: TextOverflow.ellipsis,
                                ),
                              ),
                              const SizedBox(width: 3),
                              const Icon(
                                Icons.expand_more,
                                size: 14,
                                color: AppTheme.secondaryText,
                              ),
                            ],
                          ),
                        ),
                      ),
                    ),
                  ),
                ),

                // Top Right: Info + Avatar
                Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    _buildTopIcon(
                      Icons.info_outline,
                      tooltip: 'Map Legend',
                      semanticsLabel: 'Map guide info',
                      onTap: _showMapInfoDialog,
                    ),
                    const SizedBox(width: 8),
                    _buildAvatarButton(),
                  ],
                ),
              ],
            ),
          ),

          // 3. Loading Indicator
          if (ReportRepository.instance.isLoading || _isLocating)
            Positioned(
              top: MediaQuery.of(context).padding.top + 52,
              left: 16,
              right: 16,
              child: const LinearProgressIndicator(
                minHeight: 2,
                backgroundColor: AppTheme.surface,
                color: AppTheme.actionPrimary,
              ),
            ),

          // 4. Selected Marker Preview Banner
          if (_selectedMarkerReport != null)
            Positioned(
              left: 12,
              right: 12,
              bottom: _isSheetExpanded ? 290 : 170,
              child: _buildSelectedMarkerPreviewCard(),
            ),

          // 5. Bottom Controls Column: Filter Chips, Floating Search Bar & Expandable Nearby Reports Panel
          Positioned(
            left: 12,
            right: 12,
            bottom: 12,
            child: Column(
              mainAxisSize: MainAxisSize.min,
              children: [
                _buildFilterAndRadiusRow(),
                const SizedBox(height: 6),
                _buildFloatingSearchRow(),
                const SizedBox(height: 6),
                _buildNearbyReportsPanel(),
              ],
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildFilterAndRadiusRow() {
    return SingleChildScrollView(
      scrollDirection: Axis.horizontal,
      child: Row(
        children: [
          // Status Filters
          _buildFilterChip('All', _statusFilter == 'all', () {
            _onStatusFilterSelected('all');
          }),
          const SizedBox(width: 4),
          _buildFilterChip('Missing', _statusFilter == 'missing', () {
            _onStatusFilterSelected('missing');
          }),
          const SizedBox(width: 4),
          _buildFilterChip('Found', _statusFilter == 'found', () {
            _onStatusFilterSelected('found');
          }),
          const SizedBox(width: 12),
          Container(width: 1, height: 16, color: AppTheme.borderSubtle),
          const SizedBox(width: 12),

          // Radius Filter Chips
          ...MapConfig.supportedRadiiKm.map((radius) {
            final isSelected = (_selectedRadiusKm - radius).abs() < 0.05;
            return Padding(
              padding: const EdgeInsets.only(right: 4),
              child: _buildFilterChip(
                '${radius.toStringAsFixed(1)} km',
                isSelected,
                () => _onRadiusSelected(radius),
              ),
            );
          }),
        ],
      ),
    );
  }

  Widget _buildFilterChip(String label, bool isSelected, VoidCallback onTap) {
    return Semantics(
      button: true,
      selected: isSelected,
      label: 'Filter: $label',
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(AppTheme.smallRadius),
        child: Container(
          padding: const EdgeInsets.symmetric(horizontal: 9, vertical: 5),
          decoration: BoxDecoration(
            color: isSelected
                ? AppTheme.actionPrimary
                : AppTheme.card.withValues(alpha: 0.95),
            borderRadius: BorderRadius.circular(AppTheme.smallRadius),
            border: Border.all(
              color: isSelected
                  ? AppTheme.actionPrimary
                  : AppTheme.borderSubtle,
            ),
            boxShadow: const [
              BoxShadow(
                color: Colors.black38,
                blurRadius: 4,
                offset: Offset(0, 1),
              ),
            ],
          ),
          child: Text(
            label,
            style: TextStyle(
              fontSize: 11,
              fontWeight: isSelected ? FontWeight.bold : FontWeight.w500,
              color: isSelected
                  ? AppTheme.onActionPrimary
                  : AppTheme.secondaryText,
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildSelectedMarkerPreviewCard() {
    final report = _selectedMarkerReport!;
    final isMissing = report.status == ReportStatus.missing;

    return Container(
      padding: const EdgeInsets.all(12),
      decoration: BoxDecoration(
        color: AppTheme.card,
        borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
        border: Border.all(color: AppTheme.borderHighlight),
        boxShadow: const [
          BoxShadow(
            color: Colors.black87,
            blurRadius: 16,
            offset: Offset(0, 6),
          ),
        ],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Row(
            children: [
              Container(
                padding: const EdgeInsets.all(4),
                decoration: BoxDecoration(
                  color: isMissing
                      ? AppTheme.surface
                      : AppTheme.elevatedSurface,
                  borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                  border: Border.all(color: AppTheme.borderSubtle),
                ),
                child: Icon(
                  isMissing ? Icons.search : Icons.check_circle_outline,
                  size: 14,
                  color: AppTheme.primaryText,
                ),
              ),
              const SizedBox(width: 8),
              Expanded(
                child: Text(
                  report.title,
                  style: const TextStyle(
                    fontFamily: 'Hanken Grotesk',
                    fontWeight: FontWeight.bold,
                    fontSize: 13,
                    color: AppTheme.primaryText,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              IconButton(
                icon: const Icon(Icons.close, size: 16),
                color: AppTheme.secondaryText,
                padding: EdgeInsets.zero,
                constraints: const BoxConstraints(),
                onPressed: () => setState(() => _selectedMarkerReport = null),
              ),
            ],
          ),
          const SizedBox(height: 6),
          Row(
            children: [
              Expanded(
                child: Text(
                  '${report.distance} · ${report.category}',
                  style: const TextStyle(
                    color: AppTheme.secondaryText,
                    fontSize: 11,
                  ),
                  maxLines: 1,
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              if (report.reward != null && isMissing) ...[
                const SizedBox(width: 8),
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 6,
                    vertical: 2,
                  ),
                  decoration: BoxDecoration(
                    color: AppTheme.actionPrimary,
                    borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                  ),
                  child: Text(
                    'Reward: ${report.reward}',
                    style: const TextStyle(
                      fontSize: 10,
                      fontWeight: FontWeight.bold,
                      color: AppTheme.onActionPrimary,
                    ),
                  ),
                ),
              ],
            ],
          ),
          const SizedBox(height: 10),
          SizedBox(
            width: double.infinity,
            height: 32,
            child: ElevatedButton(
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (_) => ReportDetailsScreen(
                      reportId: report.id,
                      title: report.title,
                      category: report.category,
                      distance: report.distance,
                      timeAgo: report.timeAgo,
                      status: report.status,
                      reward: report.reward,
                      description: report.description,
                      locationDescription: report.locationDescription,
                    ),
                  ),
                );
              },
              style: ElevatedButton.styleFrom(
                backgroundColor: AppTheme.actionPrimary,
                foregroundColor: AppTheme.onActionPrimary,
                shape: RoundedRectangleBorder(
                  borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                ),
                padding: EdgeInsets.zero,
              ),
              child: const Text(
                'View Details',
                style: TextStyle(fontSize: 12, fontWeight: FontWeight.bold),
              ),
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildAvatarButton() {
    final user = AuthService.instance.currentUser;
    final isMock = ReportRepository.instance.isMockMode && user == null;
    final name = (user != null && user.name.isNotEmpty)
        ? user.name
        : (isMock ? 'Alex Morgan' : 'Operator');
    final initials = user?.initials ?? (isMock ? 'AM' : 'OP');

    return Semantics(
      button: true,
      label: '$name Profile. Tap to view profile',
      child: Tooltip(
        message: '$name Profile',
        child: InkWell(
          onTap: _navigateToProfile,
          borderRadius: BorderRadius.circular(AppTheme.smallRadius),
          child: Container(
            width: 36,
            height: 36,
            decoration: BoxDecoration(
              color: AppTheme.card.withValues(alpha: 0.95),
              border: Border.all(color: AppTheme.borderSubtle),
              borderRadius: BorderRadius.circular(AppTheme.smallRadius),
              boxShadow: const [
                BoxShadow(
                  color: Colors.black45,
                  blurRadius: 6,
                  offset: Offset(0, 2),
                ),
              ],
            ),
            child: Center(
              child: Text(
                initials,
                style: const TextStyle(
                  fontSize: 11,
                  fontWeight: FontWeight.bold,
                  color: AppTheme.primaryText,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildTopIcon(
    IconData icon, {
    required String tooltip,
    required String semanticsLabel,
    required VoidCallback onTap,
  }) {
    return Semantics(
      button: true,
      label: semanticsLabel,
      child: Tooltip(
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
                  color: Colors.black45,
                  blurRadius: 6,
                  offset: Offset(0, 2),
                ),
              ],
            ),
            child: Icon(icon, size: 16, color: AppTheme.primaryText),
          ),
        ),
      ),
    );
  }

  Widget _buildFloatingSearchRow() {
    return Container(
      decoration: BoxDecoration(
        color: AppTheme.card.withValues(alpha: 0.95),
        borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
        border: Border.all(color: AppTheme.borderSubtle),
        boxShadow: const [
          BoxShadow(
            color: Colors.black45,
            blurRadius: 10,
            offset: Offset(0, 3),
          ),
        ],
      ),
      child: Row(
        children: [
          Expanded(
            child: Semantics(
              label: 'Search map items',
              child: TextField(
                controller: _mapSearchController,
                onChanged: (_) => setState(() {}),
                onSubmitted: (_) => _loadReportsForActiveArea(),
                style: const TextStyle(
                  color: AppTheme.primaryText,
                  fontSize: 13,
                ),
                decoration: InputDecoration(
                  prefixIcon: const Icon(
                    Icons.search,
                    color: AppTheme.secondaryText,
                    size: 18,
                  ),
                  hintText: 'Search items in map view...',
                  hintStyle: const TextStyle(
                    color: AppTheme.mutedText,
                    fontSize: 12,
                  ),
                  isDense: true,
                  border: InputBorder.none,
                  enabledBorder: InputBorder.none,
                  focusedBorder: InputBorder.none,
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 11,
                  ),
                ),
              ),
            ),
          ),
          Semantics(
            button: true,
            label: 'Toggle nearby reports filter panel',
            child: IconButton(
              icon: const Icon(Icons.tune, size: 18),
              color: AppTheme.primaryText,
              tooltip: 'Toggle Nearby Reports',
              onPressed: _toggleSheet,
            ),
          ),
          Semantics(
            button: true,
            label: 'Center map on device GPS position',
            child: IconButton(
              icon: _isLocating
                  ? const SizedBox(
                      width: 16,
                      height: 16,
                      child: CircularProgressIndicator(
                        strokeWidth: 2,
                        color: AppTheme.primaryText,
                      ),
                    )
                  : const Icon(Icons.near_me, size: 18),
              color: AppTheme.primaryText,
              tooltip: 'Locate Me',
              onPressed: _isLocating ? null : _requestGpsLocation,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildNearbyReportsPanel() {
    final reportsList = _filteredReports;
    final errorMessage = ReportRepository.instance.errorMessage;

    return Container(
      decoration: BoxDecoration(
        color: AppTheme.card.withValues(alpha: 0.98),
        borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
        border: Border.all(color: AppTheme.borderSubtle),
        boxShadow: const [
          BoxShadow(
            color: Colors.black54,
            blurRadius: 12,
            offset: Offset(0, 4),
          ),
        ],
      ),
      child: Column(
        mainAxisSize: MainAxisSize.min,
        children: [
          // Drag Handle
          GestureDetector(
            behavior: HitTestBehavior.opaque,
            onTap: _toggleSheet,
            child: Container(
              width: double.infinity,
              padding: const EdgeInsets.only(top: 8, bottom: 4),
              alignment: Alignment.center,
              child: Container(
                width: 32,
                height: 3,
                decoration: BoxDecoration(
                  color: AppTheme.borderMuted,
                  borderRadius: BorderRadius.circular(2),
                ),
              ),
            ),
          ),

          // Header Row
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 4),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Expanded(
                  child: Row(
                    mainAxisSize: MainAxisSize.min,
                    children: [
                      const Flexible(
                        child: Text(
                          'Nearby Reports',
                          style: TextStyle(
                            fontFamily: 'Hanken Grotesk',
                            fontWeight: FontWeight.bold,
                            fontSize: 14,
                            color: AppTheme.primaryText,
                          ),
                          maxLines: 1,
                          overflow: TextOverflow.ellipsis,
                        ),
                      ),
                      const SizedBox(width: 6),
                      Container(
                        padding: const EdgeInsets.symmetric(
                          horizontal: 6,
                          vertical: 2,
                        ),
                        decoration: BoxDecoration(
                          color: AppTheme.surface,
                          borderRadius: BorderRadius.circular(
                            AppTheme.smallRadius,
                          ),
                          border: Border.all(color: AppTheme.borderSubtle),
                        ),
                        child: Text(
                          '${ReportRepository.instance.isMockMode ? 10 + reportsList.length : reportsList.length} items',
                          style: const TextStyle(
                            fontSize: 10,
                            fontWeight: FontWeight.bold,
                            color: AppTheme.secondaryText,
                          ),
                        ),
                      ),
                    ],
                  ),
                ),
                Semantics(
                  button: true,
                  label: _isSheetExpanded
                      ? 'Collapse nearby reports'
                      : 'Expand nearby reports',
                  child: TextButton.icon(
                    onPressed: _toggleSheet,
                    style: TextButton.styleFrom(
                      foregroundColor: AppTheme.primaryText,
                      padding: const EdgeInsets.symmetric(horizontal: 4),
                      minimumSize: const Size(44, 32),
                      tapTargetSize: MaterialTapTargetSize.shrinkWrap,
                    ),
                    icon: Icon(
                      _isSheetExpanded ? Icons.expand_more : Icons.expand_less,
                      size: 16,
                    ),
                    label: Text(
                      _isSheetExpanded ? 'Collapse' : 'Expand',
                      style: const TextStyle(
                        fontSize: 11,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                  ),
                ),
              ],
            ),
          ),

          if (errorMessage != null)
            Padding(
              padding: const EdgeInsets.fromLTRB(12, 0, 12, 8),
              child: Container(
                padding: const EdgeInsets.all(8),
                decoration: BoxDecoration(
                  color: AppTheme.surface,
                  borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                  border: Border.all(color: AppTheme.borderSubtle),
                ),
                child: Row(
                  children: [
                    const Icon(
                      Icons.warning_amber_rounded,
                      size: 14,
                      color: AppTheme.primaryText,
                    ),
                    const SizedBox(width: 6),
                    Expanded(
                      child: Text(
                        errorMessage,
                        style: const TextStyle(
                          color: AppTheme.secondaryText,
                          fontSize: 11,
                        ),
                        maxLines: 2,
                        overflow: TextOverflow.ellipsis,
                      ),
                    ),
                    IconButton(
                      icon: const Icon(Icons.refresh, size: 14),
                      color: AppTheme.primaryText,
                      onPressed: () => _loadReportsForActiveArea(),
                    ),
                  ],
                ),
              ),
            ),

          // Collapsible Reports List
          AnimatedSize(
            duration: const Duration(milliseconds: 250),
            curve: Curves.easeOutCubic,
            child: _isSheetExpanded
                ? ConstrainedBox(
                    constraints: const BoxConstraints(maxHeight: 230),
                    child: reportsList.isEmpty
                        ? Padding(
                            padding: const EdgeInsets.all(20),
                            child: Center(
                              child: Text(
                                _activeAnchor != null
                                    ? 'No reports found within ${_selectedRadiusKm.toStringAsFixed(1)} km.\nTap map or increase radius.'
                                    : 'Select a location to see reports within ${_selectedRadiusKm.toStringAsFixed(1)} km.',
                                textAlign: TextAlign.center,
                                style: const TextStyle(
                                  color: AppTheme.mutedText,
                                  fontSize: 12,
                                ),
                              ),
                            ),
                          )
                        : ListView(
                            padding: const EdgeInsets.fromLTRB(12, 0, 12, 12),
                            shrinkWrap: true,
                            children: reportsList.map((r) {
                              return Padding(
                                padding: const EdgeInsets.only(bottom: 8),
                                child: _buildReportItem(report: r),
                              );
                            }).toList(),
                          ),
                  )
                : const SizedBox.shrink(),
          ),
        ],
      ),
    );
  }

  Widget _buildReportItem({required ReportModel report}) {
    final displayTitle =
        (ReportRepository.instance.isMockMode && report.id == 'REP-001')
        ? 'MacBook Pro 14 M2'
        : report.title;
    return Semantics(
      button: true,
      label:
          '$displayTitle. ${report.distance}. Status ${report.status == ReportStatus.missing ? "Missing" : "Found"}',
      child: Tooltip(
        message: displayTitle,
        child: InkWell(
          onTap: () {
            Navigator.push(
              context,
              MaterialPageRoute(
                builder: (_) => ReportDetailsScreen(
                  reportId: report.id,
                  title: displayTitle,
                  category: report.category,
                  distance: report.distance,
                  timeAgo: report.timeAgo,
                  status: report.status,
                  reward: report.reward,
                  description: report.description,
                  locationDescription: report.locationDescription,
                ),
              ),
            );
          },
          borderRadius: BorderRadius.circular(AppTheme.smallRadius),
          child: Container(
            padding: const EdgeInsets.all(10),
            decoration: BoxDecoration(
              color: AppTheme.surface,
              borderRadius: BorderRadius.circular(AppTheme.smallRadius),
              border: Border.all(color: AppTheme.borderSubtle),
            ),
            child: Row(
              children: [
                Container(
                  width: 32,
                  height: 32,
                  decoration: BoxDecoration(
                    color: AppTheme.elevatedSurface,
                    borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                    border: Border.all(color: AppTheme.borderSubtle),
                  ),
                  child: Icon(
                    report.status == ReportStatus.missing
                        ? Icons.search
                        : Icons.check_circle_outline,
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
                        displayTitle,
                        style: const TextStyle(
                          fontWeight: FontWeight.bold,
                          fontSize: 12,
                          color: AppTheme.primaryText,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(height: 2),
                      Text(
                        '${report.distance} · ${report.category}',
                        style: const TextStyle(
                          color: AppTheme.secondaryText,
                          fontSize: 11,
                        ),
                      ),
                    ],
                  ),
                ),
                const SizedBox(width: 8),
                StatusLabel(status: report.status),
              ],
            ),
          ),
        ),
      ),
    );
  }

  // Real Monochromatic FlutterMap Canvas Implementation
  Widget _buildRealMapWidget() {
    final anchor = _activeAnchor;
    final initialCenter = anchor ?? MapConfig.defaultViewportCenter;

    return FlutterMap(
      mapController: _mapController,
      options: MapOptions(
        initialCenter: initialCenter,
        initialZoom: MapConfig.defaultZoom,
        minZoom: MapConfig.minZoom,
        maxZoom: MapConfig.maxZoom,
        onTap: (tapPosition, point) => _onMapTapped(point),
      ),
      children: [
        // Monochromatic Dark Tile Layer
        TileLayer(
          urlTemplate: MapConfig.tileUrl,
          userAgentPackageName: MapConfig.userAgent,
          tileBuilder: MapConfig.darkTileBuilder,
        ),

        // Radius circle when search anchor is active
        if (anchor != null)
          CircleLayer(
            circles: [
              CircleMarker(
                point: anchor,
                radius: _selectedRadiusKm * 1000,
                useRadiusInMeter: true,
                color: const Color(0x18FFFFFF),
                borderColor: const Color(0x88FFFFFF),
                borderStrokeWidth: 1.5,
              ),
            ],
          ),

        // Monochromatic Markers Layer
        MarkerLayer(
          markers: [
            // User Anchor Marker (GPS or Manual)
            if (anchor != null)
              Marker(
                point: anchor,
                width: 32,
                height: 32,
                child: _buildAnchorMarker(),
              ),

            // Backend Report Markers
            ..._buildReportMarkers(),
          ],
        ),
      ],
    );
  }

  Widget _buildAnchorMarker() {
    return Container(
      decoration: BoxDecoration(
        shape: BoxShape.circle,
        color: const Color(0xFF080808),
        border: Border.all(color: const Color(0xFFFFFFFF), width: 2),
        boxShadow: const [
          BoxShadow(color: Colors.black87, blurRadius: 8, offset: Offset(0, 2)),
        ],
      ),
      child: Center(
        child: Container(
          width: 8,
          height: 8,
          decoration: const BoxDecoration(
            shape: BoxShape.circle,
            color: Color(0xFFFFFFFF),
          ),
        ),
      ),
    );
  }

  List<Marker> _buildReportMarkers() {
    final markers = <Marker>[];
    final reports = _filteredReports;

    for (final report in reports) {
      if (report.latitude == null || report.longitude == null) continue;

      final point = LatLng(report.latitude!, report.longitude!);
      final isSelected = _selectedMarkerReport?.id == report.id;
      final isMissing = report.status == ReportStatus.missing;

      markers.add(
        Marker(
          point: point,
          width: isSelected ? 40 : 34,
          height: isSelected ? 40 : 34,
          child: GestureDetector(
            onTap: () {
              setState(() {
                _selectedMarkerReport = report;
              });
            },
            child: Semantics(
              button: true,
              label:
                  'Map marker for ${report.title}, status: ${isMissing ? "Missing" : "Found"}',
              child: AnimatedContainer(
                duration: const Duration(milliseconds: 180),
                decoration: BoxDecoration(
                  color: isMissing
                      ? const Color(0xFF151515)
                      : const Color(0xFF222222),
                  borderRadius: BorderRadius.circular(
                    isMissing ? 6 : AppTheme.smallRadius,
                  ),
                  border: Border.all(
                    color: isSelected
                        ? const Color(0xFFFFFFFF)
                        : (isMissing
                              ? const Color(0xFFDDDDDD)
                              : const Color(0xFF777777)),
                    width: isSelected ? 2.5 : 1.5,
                  ),
                  boxShadow: [
                    BoxShadow(
                      color: isSelected
                          ? Colors.white.withValues(alpha: 0.35)
                          : Colors.black54,
                      blurRadius: isSelected ? 8 : 4,
                      offset: const Offset(0, 2),
                    ),
                  ],
                ),
                child: Center(
                  child: Icon(
                    isMissing ? Icons.help_outline : Icons.check_circle_outline,
                    size: isSelected ? 18 : 15,
                    color: isMissing
                        ? const Color(0xFFFFFFFF)
                        : const Color(0xFFAAAAAA),
                  ),
                ),
              ),
            ),
          ),
        ),
      );
    }

    return markers;
  }
}
