import 'package:flutter/material.dart';
import '../../models/report_model.dart';
import '../../services/location_service.dart';
import '../../services/report_repository.dart';
import '../../theme.dart';
import '../widgets/location_selection_sheet.dart';
import '../widgets/report_card.dart';
import 'choose_report_type_screen.dart';
import 'report_details_screen.dart';

typedef HomeReportModel = ReportModel;

class HomeScreen extends StatefulWidget {
  final ValueChanged<int>? onNavigateTab;
  final ValueChanged<String>? onInitiateCreate;

  const HomeScreen({super.key, this.onNavigateTab, this.onInitiateCreate});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  String _selectedCategory = 'All';
  String _searchQuery = '';
  String _sortBy = 'nearest';
  final TextEditingController _searchController = TextEditingController();

  final List<String> _categories = const [
    'All',
    'Electronics',
    'Documents',
    'Wallet',
    'Bag',
    'Keys',
    'Pet',
  ];

  @override
  void initState() {
    super.initState();
    ReportRepository.instance.addListener(_onReportsChanged);
    LocationService.instance.addListener(_onLocationChanged);
    final loc = LocationService.instance.currentLocation;
    if (!ReportRepository.instance.isMockMode) {
      if (loc != null) {
        ReportRepository.instance.loadReports(
          latitude: loc.latitude,
          longitude: loc.longitude,
          radiusKm: 5.0,
        );
      } else {
        ReportRepository.instance.clearGeoSearch();
      }
    }
  }

  void _onReportsChanged() {
    if (mounted) setState(() {});
  }

  void _onLocationChanged() {
    if (mounted) {
      setState(() {});
      final loc = LocationService.instance.currentLocation;
      if (!ReportRepository.instance.isMockMode) {
        if (loc != null) {
          ReportRepository.instance.loadReports(
            latitude: loc.latitude,
            longitude: loc.longitude,
            radiusKm: 5.0,
          );
        } else {
          ReportRepository.instance.clearGeoSearch();
        }
      }
    }
  }

  @override
  void dispose() {
    ReportRepository.instance.removeListener(_onReportsChanged);
    LocationService.instance.removeListener(_onLocationChanged);
    _searchController.dispose();
    super.dispose();
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

  List<ReportModel> get _allReports {
    if (!LocationService.instance.hasLocation &&
        !ReportRepository.instance.isMockMode) {
      return const <ReportModel>[];
    }
    return ReportRepository.instance.reports;
  }

  List<HomeReportModel> get _filteredReports {
    final list = _allReports.where((item) {
      final matchesCategory =
          _selectedCategory == 'All' ||
          item.category.toLowerCase() == _selectedCategory.toLowerCase();
      final query = _searchQuery.trim().toLowerCase();
      final matchesSearch =
          query.isEmpty ||
          item.title.toLowerCase().contains(query) ||
          item.category.toLowerCase().contains(query) ||
          item.locationDescription.toLowerCase().contains(query) ||
          item.description.toLowerCase().contains(query);
      return matchesCategory && matchesSearch;
    }).toList();

    if (_sortBy == 'reward') {
      list.sort((a, b) {
        final aReward =
            int.tryParse(a.reward?.replaceAll(RegExp(r'[^\d]'), '') ?? '0') ??
            0;
        final bReward =
            int.tryParse(b.reward?.replaceAll(RegExp(r'[^\d]'), '') ?? '0') ??
            0;
        return bReward.compareTo(aReward);
      });
    }

    return list;
  }

  void _showLocationPicker() {
    LocationSelectionSheet.show(
      context,
      onPickOnMap: () => widget.onNavigateTab?.call(1),
      onLocationChanged: () {
        final loc = LocationService.instance.currentLocation;
        if (!ReportRepository.instance.isMockMode) {
          if (loc != null) {
            ReportRepository.instance.loadReports(
              forceRefresh: true,
              latitude: loc.latitude,
              longitude: loc.longitude,
              radiusKm: 5.0,
            );
          } else {
            ReportRepository.instance.clearGeoSearch();
          }
        }
        if (mounted) setState(() {});
      },
    );
  }

  void _showFilterSheet() {
    showModalBottomSheet(
      context: context,
      backgroundColor: AppTheme.card,
      shape: const RoundedRectangleBorder(
        borderRadius: BorderRadius.vertical(top: Radius.circular(16)),
        side: BorderSide(color: AppTheme.borderSubtle),
      ),
      builder: (ctx) {
        return StatefulBuilder(
          builder: (context, setSheetState) {
            return SafeArea(
              child: Padding(
                padding: const EdgeInsets.all(20),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        const Text(
                          'Sort & Filters',
                          style: TextStyle(
                            fontFamily: 'Hanken Grotesk',
                            fontSize: 16,
                            fontWeight: FontWeight.bold,
                            color: AppTheme.primaryText,
                          ),
                        ),
                        TextButton(
                          onPressed: () {
                            setState(() {
                              _sortBy = 'nearest';
                              _selectedCategory = 'All';
                            });
                            Navigator.pop(ctx);
                          },
                          child: const Text(
                            'Reset',
                            style: TextStyle(color: AppTheme.secondaryText),
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 12),
                    const Text(
                      'SORT BY',
                      style: TextStyle(
                        fontSize: 10,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 1.0,
                        color: AppTheme.secondaryText,
                      ),
                    ),
                    const SizedBox(height: 8),
                    Wrap(
                      spacing: 8,
                      children: [
                        _buildSortChip(
                          'nearest',
                          'Nearest Distance',
                          setSheetState,
                        ),
                        _buildSortChip('newest', 'Most Recent', setSheetState),
                        _buildSortChip(
                          'reward',
                          'Highest Reward',
                          setSheetState,
                        ),
                      ],
                    ),
                    const SizedBox(height: 20),
                    SizedBox(
                      width: double.infinity,
                      child: ElevatedButton(
                        onPressed: () => Navigator.pop(ctx),
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppTheme.actionPrimary,
                          foregroundColor: AppTheme.onActionPrimary,
                          padding: const EdgeInsets.symmetric(vertical: 12),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(
                              AppTheme.smallRadius,
                            ),
                          ),
                        ),
                        child: const Text(
                          'Apply Filters',
                          style: TextStyle(fontWeight: FontWeight.bold),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
            );
          },
        );
      },
    );
  }

  Widget _buildSortChip(String value, String label, StateSetter setSheetState) {
    final isSelected = _sortBy == value;
    return ChoiceChip(
      label: Text(label),
      selected: isSelected,
      onSelected: (selected) {
        if (selected) {
          setSheetState(() => _sortBy = value);
          setState(() => _sortBy = value);
        }
      },
      selectedColor: AppTheme.actionPrimary,
      backgroundColor: AppTheme.surface,
      labelStyle: TextStyle(
        color: isSelected ? AppTheme.onActionPrimary : AppTheme.secondaryText,
        fontWeight: isSelected ? FontWeight.bold : FontWeight.normal,
        fontSize: 12,
      ),
      side: BorderSide(
        color: isSelected ? Colors.transparent : AppTheme.borderSubtle,
      ),
      shape: RoundedRectangleBorder(
        borderRadius: BorderRadius.circular(AppTheme.smallRadius),
      ),
    );
  }

  void _openCreateFlow(String type) {
    if (widget.onInitiateCreate != null) {
      widget.onInitiateCreate!(type);
    } else {
      Navigator.push(
        context,
        MaterialPageRoute(
          builder: (_) => ChooseReportTypeScreen(initialType: type),
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final reports = _filteredReports;

    return Scaffold(
      backgroundColor: AppTheme.background,
      body: SafeArea(
        child: RefreshIndicator(
          onRefresh: () async {
            final loc = LocationService.instance.currentLocation;
            if (loc != null) {
              await ReportRepository.instance.loadReports(
                forceRefresh: true,
                latitude: loc.latitude,
                longitude: loc.longitude,
                radiusKm: 5.0,
              );
            } else {
              ReportRepository.instance.clearGeoSearch();
            }
          },
          color: AppTheme.actionPrimary,
          backgroundColor: AppTheme.card,
          child: SingleChildScrollView(
            physics: const AlwaysScrollableScrollPhysics(),
            padding: const EdgeInsets.symmetric(
              horizontal: AppTheme.spacingMd,
              vertical: 14,
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Editorial Mobile Header: Brand + Location Selector
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  crossAxisAlignment: CrossAxisAlignment.center,
                  children: [
                    Row(
                      mainAxisSize: MainAxisSize.min,
                      children: [
                        const Text(
                          'Boomerang',
                          style: TextStyle(
                            fontFamily: 'Hanken Grotesk',
                            fontSize: 24,
                            fontWeight: FontWeight.bold,
                            letterSpacing: -0.5,
                            color: AppTheme.primaryText,
                          ),
                        ),
                        const SizedBox(width: 6),
                        Container(
                          width: 5,
                          height: 5,
                          decoration: const BoxDecoration(
                            color: AppTheme.actionPrimary,
                            shape: BoxShape.circle,
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(width: 8),
                    Flexible(
                      child: Semantics(
                        button: true,
                        label:
                            'Current location: $_locationLabel. Tap to change',
                        child: Tooltip(
                          message: 'Select Location',
                          child: InkWell(
                            onTap: _showLocationPicker,
                            borderRadius: BorderRadius.circular(
                              AppTheme.smallRadius,
                            ),
                            child: Container(
                              padding: const EdgeInsets.symmetric(
                                horizontal: 10,
                                vertical: 6,
                              ),
                              decoration: BoxDecoration(
                                color: AppTheme.card,
                                border: Border.all(
                                  color: AppTheme.borderSubtle,
                                ),
                                borderRadius: BorderRadius.circular(
                                  AppTheme.smallRadius,
                                ),
                              ),
                              child: Row(
                                mainAxisSize: MainAxisSize.min,
                                children: [
                                  Icon(
                                    LocationService.instance.hasLocation
                                        ? Icons.location_on
                                        : Icons.location_searching,
                                    size: 14,
                                    color: AppTheme.secondaryText,
                                  ),
                                  const SizedBox(width: 4),
                                  Flexible(
                                    child: Text(
                                      _locationLabel,
                                      style: const TextStyle(
                                        fontSize: 12,
                                        fontWeight: FontWeight.w500,
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
                  ],
                ),
                const SizedBox(height: 14),

                // Search Bar
                Semantics(
                  label: 'Search missing and found items',
                  child: TextField(
                    controller: _searchController,
                    onChanged: (val) => setState(() => _searchQuery = val),
                    style: const TextStyle(
                      color: AppTheme.primaryText,
                      fontSize: 14,
                    ),
                    decoration: InputDecoration(
                      prefixIcon: const Icon(
                        Icons.search,
                        color: AppTheme.secondaryText,
                        size: 20,
                      ),
                      hintText: 'Search missing and found items...',
                      suffixIcon: _searchQuery.isNotEmpty
                          ? IconButton(
                              icon: const Icon(
                                Icons.clear,
                                size: 18,
                                color: AppTheme.secondaryText,
                              ),
                              tooltip: 'Clear search',
                              onPressed: () {
                                setState(() {
                                  _searchController.clear();
                                  _searchQuery = '';
                                });
                              },
                            )
                          : IconButton(
                              icon: const Icon(
                                Icons.tune,
                                size: 18,
                                color: AppTheme.secondaryText,
                              ),
                              tooltip: 'Filter & sort settings',
                              onPressed: _showFilterSheet,
                            ),
                      filled: true,
                      fillColor: AppTheme.card,
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 12,
                      ),
                      border: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(
                          AppTheme.defaultRadius,
                        ),
                        borderSide: const BorderSide(
                          color: AppTheme.borderSubtle,
                        ),
                      ),
                      enabledBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(
                          AppTheme.defaultRadius,
                        ),
                        borderSide: const BorderSide(
                          color: AppTheme.borderSubtle,
                        ),
                      ),
                      focusedBorder: OutlineInputBorder(
                        borderRadius: BorderRadius.circular(
                          AppTheme.defaultRadius,
                        ),
                        borderSide: const BorderSide(
                          color: AppTheme.actionPrimary,
                        ),
                      ),
                    ),
                  ),
                ),
                const SizedBox(height: 14),

                // Quick Action Reporting Entry Points (Touch-friendly 48px+ cards)
                Row(
                  children: [
                    Expanded(
                      child: _buildActionCard(
                        title: 'Report Missing',
                        subtitle: 'Lost an item',
                        icon: Icons.search,
                        isPrimary: true,
                        onTap: () => _openCreateFlow('missing'),
                      ),
                    ),
                    const SizedBox(width: 10),
                    Expanded(
                      child: _buildActionCard(
                        title: 'Report Found',
                        subtitle: 'Found an item',
                        icon: Icons.inventory_2_outlined,
                        isPrimary: false,
                        onTap: () => _openCreateFlow('found'),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 16),

                // Horizontally Scrollable Categories
                SingleChildScrollView(
                  scrollDirection: Axis.horizontal,
                  child: Row(
                    children: _categories.map((cat) {
                      return _buildCategoryPill(
                        cat,
                        isSelected: _selectedCategory == cat,
                        onTap: () => setState(() => _selectedCategory = cat),
                      );
                    }).toList(),
                  ),
                ),
                const SizedBox(height: 20),

                // Nearby Reports Header
                Row(
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
                                fontSize: 17,
                                fontWeight: FontWeight.bold,
                                letterSpacing: -0.3,
                                color: AppTheme.primaryText,
                              ),
                              maxLines: 1,
                              overflow: TextOverflow.ellipsis,
                            ),
                          ),
                          const SizedBox(width: 8),
                          Container(
                            padding: const EdgeInsets.symmetric(
                              horizontal: 7,
                              vertical: 2,
                            ),
                            decoration: BoxDecoration(
                              color: AppTheme.card,
                              borderRadius: BorderRadius.circular(
                                AppTheme.smallRadius,
                              ),
                              border: Border.all(color: AppTheme.borderSubtle),
                            ),
                            child: Text(
                              '${reports.length} items',
                              style: const TextStyle(
                                fontSize: 11,
                                color: AppTheme.secondaryText,
                                fontWeight: FontWeight.w500,
                              ),
                            ),
                          ),
                        ],
                      ),
                    ),
                    Semantics(
                      button: true,
                      label: 'Switch to Map tab',
                      child: Tooltip(
                        message: 'Map View',
                        child: TextButton.icon(
                          onPressed: () {
                            widget.onNavigateTab?.call(1);
                          },
                          icon: const Text(
                            'Map View',
                            style: TextStyle(
                              fontSize: 12,
                              fontWeight: FontWeight.bold,
                            ),
                          ),
                          label: const Icon(Icons.map_outlined, size: 15),
                          style: TextButton.styleFrom(
                            foregroundColor: AppTheme.primaryText,
                            minimumSize: const Size(44, 44),
                            padding: const EdgeInsets.symmetric(
                              horizontal: 8,
                              vertical: 8,
                            ),
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 10),

                // Vertical Reports Feed
                if (ReportRepository.instance.isLoading && reports.isEmpty)
                  Container(
                    margin: const EdgeInsets.symmetric(vertical: 36),
                    alignment: Alignment.center,
                    child: const CircularProgressIndicator(
                      color: AppTheme.primaryText,
                    ),
                  )
                else if (ReportRepository.instance.errorMessage != null &&
                    reports.isEmpty)
                  Container(
                    margin: const EdgeInsets.symmetric(vertical: 24),
                    padding: const EdgeInsets.all(24),
                    decoration: BoxDecoration(
                      color: AppTheme.card,
                      borderRadius: BorderRadius.circular(
                        AppTheme.defaultRadius,
                      ),
                      border: Border.all(color: AppTheme.borderSubtle),
                    ),
                    alignment: Alignment.center,
                    child: Column(
                      children: [
                        const Icon(
                          Icons.cloud_off_outlined,
                          size: 36,
                          color: AppTheme.secondaryText,
                        ),
                        const SizedBox(height: 12),
                        const Text(
                          'Unable to load live reports',
                          style: TextStyle(
                            fontFamily: 'Hanken Grotesk',
                            color: AppTheme.primaryText,
                            fontWeight: FontWeight.bold,
                            fontSize: 15,
                          ),
                        ),
                        const SizedBox(height: 6),
                        Text(
                          ReportRepository.instance.errorMessage!,
                          textAlign: TextAlign.center,
                          style: const TextStyle(
                            color: AppTheme.secondaryText,
                            fontSize: 12,
                          ),
                        ),
                        const SizedBox(height: 16),
                        ElevatedButton(
                          onPressed: () {
                            final loc =
                                LocationService.instance.currentLocation;
                            if (loc != null) {
                              ReportRepository.instance.loadReports(
                                forceRefresh: true,
                                latitude: loc.latitude,
                                longitude: loc.longitude,
                                radiusKm: 5.0,
                              );
                            } else {
                              ReportRepository.instance.clearGeoSearch();
                            }
                          },
                          style: ElevatedButton.styleFrom(
                            backgroundColor: AppTheme.actionPrimary,
                            foregroundColor: AppTheme.onActionPrimary,
                          ),
                          child: const Text('Retry'),
                        ),
                      ],
                    ),
                  )
                else if (reports.isEmpty &&
                    !LocationService.instance.hasLocation &&
                    !ReportRepository.instance.isMockMode)
                  Container(
                    margin: const EdgeInsets.symmetric(vertical: 24),
                    padding: const EdgeInsets.all(24),
                    decoration: BoxDecoration(
                      color: AppTheme.card,
                      borderRadius: BorderRadius.circular(
                        AppTheme.defaultRadius,
                      ),
                      border: Border.all(color: AppTheme.borderSubtle),
                    ),
                    alignment: Alignment.center,
                    child: Column(
                      children: [
                        const Icon(
                          Icons.location_searching,
                          size: 36,
                          color: AppTheme.secondaryText,
                        ),
                        const SizedBox(height: 12),
                        const Text(
                          'Select a location to see reports within 5 km.',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            fontFamily: 'Hanken Grotesk',
                            color: AppTheme.primaryText,
                            fontWeight: FontWeight.bold,
                            fontSize: 15,
                          ),
                        ),
                        const SizedBox(height: 6),
                        const Text(
                          'Boomerang surfaces reports within a 5 km radius of your location. Select or detect your location to view nearby items.',
                          textAlign: TextAlign.center,
                          style: TextStyle(
                            color: AppTheme.secondaryText,
                            fontSize: 12,
                          ),
                        ),
                        const SizedBox(height: 16),
                        ElevatedButton.icon(
                          onPressed: _showLocationPicker,
                          icon: const Icon(Icons.my_location, size: 16),
                          label: const Text('Select Location'),
                          style: ElevatedButton.styleFrom(
                            backgroundColor: AppTheme.actionPrimary,
                            foregroundColor: AppTheme.onActionPrimary,
                            padding: const EdgeInsets.symmetric(
                              horizontal: 20,
                              vertical: 12,
                            ),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(
                                AppTheme.smallRadius,
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                  )
                else if (reports.isEmpty)
                  Container(
                    margin: const EdgeInsets.symmetric(vertical: 24),
                    padding: const EdgeInsets.all(24),
                    decoration: BoxDecoration(
                      color: AppTheme.card,
                      borderRadius: BorderRadius.circular(
                        AppTheme.defaultRadius,
                      ),
                      border: Border.all(color: AppTheme.borderSubtle),
                    ),
                    alignment: Alignment.center,
                    child: Column(
                      children: [
                        const Icon(
                          Icons.search_off,
                          size: 36,
                          color: AppTheme.secondaryText,
                        ),
                        const SizedBox(height: 12),
                        Text(
                          _searchQuery.isNotEmpty
                              ? 'No reports matching "$_searchQuery"'
                              : (LocationService.instance.hasLocation
                                    ? 'No reports within 5 km of $_locationLabel'
                                    : 'No reports found'),
                          style: const TextStyle(
                            fontFamily: 'Hanken Grotesk',
                            color: AppTheme.primaryText,
                            fontWeight: FontWeight.bold,
                            fontSize: 15,
                          ),
                          textAlign: TextAlign.center,
                        ),
                        const SizedBox(height: 4),
                        Text(
                          'Category: $_selectedCategory',
                          style: const TextStyle(
                            color: AppTheme.secondaryText,
                            fontSize: 12,
                          ),
                        ),
                      ],
                    ),
                  )
                else
                  ...reports.map((report) {
                    return Padding(
                      padding: const EdgeInsets.only(bottom: 10),
                      child: ReportCard(
                        title: report.title,
                        category: report.category,
                        distance: report.distance,
                        timeAgo: report.timeAgo,
                        status: report.status,
                        reward: report.reward,
                        onTap: () {
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
                      ),
                    );
                  }),
                const SizedBox(height: 20),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildActionCard({
    required String title,
    required String subtitle,
    required IconData icon,
    required bool isPrimary,
    required VoidCallback onTap,
  }) {
    return Semantics(
      button: true,
      label: '$title. $subtitle',
      child: Tooltip(
        message: title,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
          child: Container(
            constraints: const BoxConstraints(minHeight: 64),
            padding: const EdgeInsets.all(12),
            decoration: BoxDecoration(
              color: isPrimary ? AppTheme.elevatedSurface : AppTheme.card,
              border: Border.all(
                color: isPrimary ? AppTheme.borderMuted : AppTheme.borderSubtle,
              ),
              borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
            ),
            child: Row(
              children: [
                Container(
                  width: 36,
                  height: 36,
                  decoration: BoxDecoration(
                    color: isPrimary ? AppTheme.card : AppTheme.surface,
                    borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                    border: Border.all(color: AppTheme.borderSubtle),
                  ),
                  child: Icon(icon, size: 18, color: AppTheme.primaryText),
                ),
                const SizedBox(width: 10),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Text(
                        title,
                        style: const TextStyle(
                          fontFamily: 'Hanken Grotesk',
                          fontWeight: FontWeight.bold,
                          fontSize: 13,
                          color: AppTheme.primaryText,
                        ),
                        maxLines: 1,
                        overflow: TextOverflow.ellipsis,
                      ),
                      const SizedBox(height: 2),
                      Text(
                        subtitle,
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
        ),
      ),
    );
  }

  Widget _buildCategoryPill(
    String category, {
    required bool isSelected,
    required VoidCallback onTap,
  }) {
    return Padding(
      padding: const EdgeInsets.only(right: 8),
      child: Semantics(
        button: true,
        label: 'Filter by $category',
        selected: isSelected,
        child: Tooltip(
          message: 'Category: $category',
          child: InkWell(
            onTap: onTap,
            borderRadius: BorderRadius.circular(AppTheme.smallRadius),
            child: Container(
              constraints: const BoxConstraints(minHeight: 34),
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 7),
              decoration: BoxDecoration(
                color: isSelected ? AppTheme.actionPrimary : AppTheme.card,
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                border: Border.all(
                  color: isSelected
                      ? Colors.transparent
                      : AppTheme.borderSubtle,
                ),
              ),
              child: Text(
                category,
                style: TextStyle(
                  fontSize: 12,
                  fontWeight: isSelected ? FontWeight.bold : FontWeight.w500,
                  color: isSelected
                      ? AppTheme.onActionPrimary
                      : AppTheme.secondaryText,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
