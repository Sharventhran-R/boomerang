import 'package:flutter/material.dart';
import '../../models/report_model.dart';
import '../../services/auth_service.dart';
import '../../services/recovery_repository.dart';
import '../../services/report_repository.dart';
import '../../theme.dart';
import '../widgets/app_toast.dart';
import '../widgets/report_card.dart';
import '../widgets/status_label.dart';
import 'login_screen.dart';
import 'recovery_requests_screen.dart';
import 'report_details_screen.dart';

class MyReportsScreen extends StatefulWidget {
  const MyReportsScreen({super.key});

  @override
  State<MyReportsScreen> createState() => _MyReportsScreenState();
}

class _MyReportsScreenState extends State<MyReportsScreen> {
  String _selectedFilter = 'all';

  @override
  void initState() {
    super.initState();
    ReportRepository.instance.addListener(_onReportsChanged);
    RecoveryRepository.instance.addListener(_onReportsChanged);
    if (!ReportRepository.instance.isMockMode &&
        !ReportRepository.instance.hasLoaded) {
      ReportRepository.instance.loadReports();
    }
  }

  void _onReportsChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    ReportRepository.instance.removeListener(_onReportsChanged);
    RecoveryRepository.instance.removeListener(_onReportsChanged);
    super.dispose();
  }

  void _openDetails(ReportModel r) {
    Navigator.push(
      context,
      MaterialPageRoute(
        builder: (_) => ReportDetailsScreen(
          reportId: r.id,
          title: r.title,
          category: r.category,
          distance: r.distance,
          timeAgo: r.timeAgo,
          status: r.status,
          reward: r.reward,
          description: r.description,
          locationDescription: r.locationDescription,
        ),
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    final allUserReports = ReportRepository.instance.userReports;
    final missingCount = allUserReports
        .where((r) => r.status == ReportStatus.missing)
        .length;
    final foundCount = allUserReports
        .where((r) => r.status == ReportStatus.found)
        .length;

    final filteredReports = allUserReports.where((r) {
      if (_selectedFilter == 'missing') return r.status == ReportStatus.missing;
      if (_selectedFilter == 'found') return r.status == ReportStatus.found;
      return true;
    }).toList();

    return Scaffold(
      backgroundColor: AppTheme.background,
      body: SafeArea(
        child: CustomScrollView(
          slivers: [
            SliverToBoxAdapter(
              child: Padding(
                padding: const EdgeInsets.fromLTRB(16, 16, 16, 8),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Row(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      mainAxisAlignment: MainAxisAlignment.spaceBetween,
                      children: [
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'My Reports',
                                style: Theme.of(context)
                                    .textTheme
                                    .headlineMedium
                                    ?.copyWith(
                                      fontFamily: 'Hanken Grotesk',
                                      color: AppTheme.primaryText,
                                      fontWeight: FontWeight.bold,
                                      letterSpacing: -0.5,
                                    ),
                              ),
                              const SizedBox(height: 4),
                              const Text(
                                'Manage your reported items and active status',
                                style: TextStyle(
                                  color: AppTheme.secondaryText,
                                  fontSize: 12,
                                ),
                              ),
                            ],
                          ),
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 10,
                            vertical: 5,
                          ),
                          decoration: BoxDecoration(
                            color: AppTheme.card,
                            borderRadius: BorderRadius.circular(
                              AppTheme.smallRadius,
                            ),
                            border: Border.all(color: AppTheme.borderSubtle),
                          ),
                          child: Row(
                            mainAxisSize: MainAxisSize.min,
                            children: [
                              Container(
                                width: 6,
                                height: 6,
                                decoration: const BoxDecoration(
                                  color: AppTheme.actionPrimary,
                                  shape: BoxShape.circle,
                                ),
                              ),
                              const SizedBox(width: 6),
                              Text(
                                '${allUserReports.length} ACTIVE',
                                style: const TextStyle(
                                  fontSize: 10,
                                  fontWeight: FontWeight.bold,
                                  letterSpacing: 1.0,
                                  color: AppTheme.primaryText,
                                ),
                              ),
                            ],
                          ),
                        ),
                      ],
                    ),
                    const SizedBox(height: 16),
                    SingleChildScrollView(
                      scrollDirection: Axis.horizontal,
                      child: Row(
                        children: [
                          _buildFilterTab(
                            'all',
                            'All (${allUserReports.length})',
                          ),
                          const SizedBox(width: 8),
                          _buildFilterTab('missing', 'Missing ($missingCount)'),
                          const SizedBox(width: 8),
                          _buildFilterTab('found', 'Found ($foundCount)'),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                  ],
                ),
              ),
            ),
            SliverPadding(
              padding: const EdgeInsets.symmetric(horizontal: 16),
              sliver: SliverList(
                delegate: SliverChildListDelegate([
                  if (!AuthService.instance.isAuthenticated &&
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
                            Icons.lock_outline,
                            size: 32,
                            color: AppTheme.secondaryText,
                          ),
                          const SizedBox(height: 10),
                          const Text(
                            'Authentication Required',
                            style: TextStyle(
                              fontFamily: 'Hanken Grotesk',
                              fontWeight: FontWeight.bold,
                              fontSize: 15,
                              color: AppTheme.primaryText,
                            ),
                          ),
                          const SizedBox(height: 6),
                          const Text(
                            'Log in to view and manage your verified incident reports.',
                            textAlign: TextAlign.center,
                            style: TextStyle(
                              color: AppTheme.secondaryText,
                              fontSize: 12,
                            ),
                          ),
                          const SizedBox(height: 14),
                          ElevatedButton(
                            onPressed: () => Navigator.push(
                              context,
                              MaterialPageRoute(
                                builder: (_) => const LoginScreen(),
                              ),
                            ),
                            style: ElevatedButton.styleFrom(
                              backgroundColor: AppTheme.actionPrimary,
                              foregroundColor: AppTheme.onActionPrimary,
                            ),
                            child: const Text('Log In'),
                          ),
                        ],
                      ),
                    )
                  else if (filteredReports.isEmpty)
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
                      child: const Text(
                        'No reports matching this filter.',
                        style: TextStyle(
                          color: AppTheme.secondaryText,
                          fontSize: 13,
                        ),
                      ),
                    )
                  else
                    ...filteredReports.map((r) {
                      final hasPendingRequests = RecoveryRepository
                          .instance
                          .receivedRequests
                          .any(
                            (req) =>
                                (req.reportId == r.id ||
                                    (RecoveryRepository.instance.isMockMode &&
                                        r.id == 'REP-001' &&
                                        req.reportId == 'rep-8941')) &&
                                req.status.toLowerCase() == 'pending',
                          );
                      final isPending = hasPendingRequests;
                      return Padding(
                        padding: const EdgeInsets.only(bottom: 12),
                        child: ReportCard(
                          title: r.title,
                          category: '${r.category} · ${r.locationDescription}',
                          distance: r.timeAgo,
                          timeAgo: '',
                          status: r.status,
                          reward: r.reward,
                          onTap: () => _openDetails(r),
                          bottomActions: isPending
                              ? Column(
                                  children: [
                                    InkWell(
                                      onTap: () {
                                        Navigator.push(
                                          context,
                                          MaterialPageRoute(
                                            builder: (_) =>
                                                const RecoveryRequestsScreen(),
                                          ),
                                        );
                                      },
                                      child: Container(
                                        padding: const EdgeInsets.symmetric(
                                          horizontal: 12,
                                          vertical: 8,
                                        ),
                                        decoration: BoxDecoration(
                                          color: AppTheme.elevatedSurface,
                                          borderRadius: BorderRadius.circular(
                                            AppTheme.smallRadius,
                                          ),
                                          border: Border.all(
                                            color: AppTheme.borderMuted,
                                          ),
                                        ),
                                        child: const Row(
                                          children: [
                                            Icon(
                                              Icons.mark_email_unread,
                                              size: 16,
                                              color: AppTheme.primaryText,
                                            ),
                                            SizedBox(width: 8),
                                            Expanded(
                                              child: Text(
                                                '1 Pending Recovery Request',
                                                style: TextStyle(
                                                  color: AppTheme.primaryText,
                                                  fontSize: 12,
                                                  fontWeight: FontWeight.bold,
                                                ),
                                              ),
                                            ),
                                            Icon(
                                              Icons.chevron_right,
                                              size: 16,
                                              color: AppTheme.secondaryText,
                                            ),
                                          ],
                                        ),
                                      ),
                                    ),
                                    const SizedBox(height: 8),
                                    Row(
                                      children: [
                                        Expanded(
                                          child: _buildActionButton(
                                            icon: Icons.visibility,
                                            label: 'View Details',
                                            color: AppTheme.elevatedSurface,
                                            textColor: AppTheme.primaryText,
                                            onTap: () => _openDetails(r),
                                          ),
                                        ),
                                        const SizedBox(width: 8),
                                        Expanded(
                                          child: _buildActionButton(
                                            icon: Icons.edit_note,
                                            label: 'Edit Report',
                                            color: AppTheme.surface,
                                            textColor: AppTheme.secondaryText,
                                            onTap: () {
                                              AppToast.info(
                                                context,
                                                message:
                                                    'Telemetry record #${r.id} is locked in this session.',
                                              );
                                            },
                                          ),
                                        ),
                                      ],
                                    ),
                                  ],
                                )
                              : Row(
                                  children: [
                                    Expanded(
                                      child: _buildActionButton(
                                        icon: Icons.visibility,
                                        label: 'View Details',
                                        color: AppTheme.elevatedSurface,
                                        textColor: AppTheme.primaryText,
                                        onTap: () => _openDetails(r),
                                      ),
                                    ),
                                    const SizedBox(width: 8),
                                    Expanded(
                                      child: _buildActionButton(
                                        icon: Icons.edit_note,
                                        label: 'Edit Report',
                                        color: AppTheme.surface,
                                        textColor: AppTheme.secondaryText,
                                        onTap: () {
                                          AppToast.info(
                                            context,
                                            message:
                                                'Telemetry record #${r.id} is locked in this session.',
                                          );
                                        },
                                      ),
                                    ),
                                  ],
                                ),
                        ),
                      );
                    }),
                  const SizedBox(height: 120), // Space for bottom nav
                ]),
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _buildFilterTab(String id, String label) {
    final isSelected = _selectedFilter == id;
    return Semantics(
      button: true,
      label: 'Filter reports: $label',
      selected: isSelected,
      child: Tooltip(
        message: 'Show $label',
        child: InkWell(
          onTap: () => setState(() => _selectedFilter = id),
          borderRadius: BorderRadius.circular(AppTheme.smallRadius),
          child: Container(
            constraints: const BoxConstraints(minHeight: 40),
            padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: isSelected ? AppTheme.actionPrimary : AppTheme.card,
              borderRadius: BorderRadius.circular(AppTheme.smallRadius),
              border: Border.all(
                color: isSelected ? Colors.transparent : AppTheme.borderSubtle,
              ),
            ),
            child: Text(
              label,
              style: TextStyle(
                color: isSelected
                    ? AppTheme.onActionPrimary
                    : AppTheme.secondaryText,
                fontSize: 12,
                fontWeight: isSelected ? FontWeight.bold : FontWeight.w500,
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildActionButton({
    required IconData icon,
    required String label,
    required Color color,
    required Color textColor,
    VoidCallback? onTap,
  }) {
    return Semantics(
      button: true,
      label: label,
      child: Tooltip(
        message: label,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(AppTheme.smallRadius),
          child: Container(
            constraints: const BoxConstraints(minHeight: 40),
            padding: const EdgeInsets.symmetric(vertical: 8, horizontal: 12),
            alignment: Alignment.center,
            decoration: BoxDecoration(
              color: color,
              borderRadius: BorderRadius.circular(AppTheme.smallRadius),
              border: Border.all(color: AppTheme.borderSubtle),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.center,
              mainAxisSize: MainAxisSize.min,
              children: [
                Icon(icon, size: 15, color: textColor),
                const SizedBox(width: 5),
                Flexible(
                  child: Text(
                    label,
                    maxLines: 1,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      color: textColor,
                      fontSize: 12,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
