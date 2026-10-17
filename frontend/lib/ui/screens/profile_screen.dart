import 'package:flutter/material.dart';
import '../../services/auth_service.dart';
import '../../services/recovery_repository.dart';
import '../../services/report_repository.dart';
import '../../theme.dart';
import '../widgets/app_toast.dart';
import '../widgets/status_label.dart';
import 'my_reports_screen.dart';
import 'recovery_requests_screen.dart';
import 'session_expired_screen.dart';
import 'settings_screen.dart';

class ProfileScreen extends StatefulWidget {
  final ValueChanged<int>? onNavigateTab;

  const ProfileScreen({super.key, this.onNavigateTab});

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  @override
  void initState() {
    super.initState();
    AuthService.instance.addListener(_onStateChanged);
    ReportRepository.instance.addListener(_onStateChanged);
    RecoveryRepository.instance.addListener(_onStateChanged);
    if (AuthService.instance.isAuthenticated) {
      if (!ReportRepository.instance.isMockMode) {
        ReportRepository.instance.loadReports(forceRefresh: true);
        RecoveryRepository.instance.loadRequests();
      }
    }
  }

  void _onStateChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    AuthService.instance.removeListener(_onStateChanged);
    ReportRepository.instance.removeListener(_onStateChanged);
    RecoveryRepository.instance.removeListener(_onStateChanged);
    super.dispose();
  }

  void _showLogoutDialog(BuildContext context) {
    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppTheme.card,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
          side: const BorderSide(color: AppTheme.borderSubtle),
        ),
        title: const Text(
          'Confirm Session Termination',
          style: TextStyle(
            color: AppTheme.primaryText,
            fontWeight: FontWeight.bold,
          ),
        ),
        content: const Text(
          'Are you sure you want to end your active session and log out of Boomerang?',
          style: TextStyle(color: AppTheme.secondaryText, height: 1.4),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.pop(ctx),
            child: const Text(
              'Cancel',
              style: TextStyle(color: AppTheme.secondaryText),
            ),
          ),
          ElevatedButton(
            onPressed: () async {
              Navigator.pop(ctx);
              await AuthService.instance.logout();
              await ReportRepository.instance.loadReports(forceRefresh: true);
              if (context.mounted) {
                Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (context) => const SessionExpiredScreen(),
                  ),
                );
              }
            },
            style: ElevatedButton.styleFrom(
              backgroundColor: AppTheme.actionPrimary,
              foregroundColor: AppTheme.onActionPrimary,
              shape: RoundedRectangleBorder(
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
              ),
            ),
            child: const Text('Log Out'),
          ),
        ],
      ),
    );
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        backgroundColor: AppTheme.card,
        elevation: 0,
        title: const Text(
          'Profile',
          style: TextStyle(
            color: AppTheme.primaryText,
            fontWeight: FontWeight.w600,
            fontSize: 16,
          ),
        ),
        actions: [
          Tooltip(
            message: 'Settings',
            child: IconButton(
              icon: const Icon(Icons.settings, color: AppTheme.secondaryText),
              tooltip: 'Settings',
              onPressed: () {
                Navigator.push(
                  context,
                  MaterialPageRoute(
                    builder: (context) => const SettingsScreen(),
                  ),
                );
              },
            ),
          ),
        ],
      ),
      body: SafeArea(
        child: ListenableBuilder(
          listenable: AuthService.instance,
          builder: (context, _) {
            final user = AuthService.instance.currentUser;
            final isMock = ReportRepository.instance.isMockMode && user == null;
            final initials = user?.initials ?? (isMock ? 'AM' : 'OP');
            final name = user?.name ?? (isMock ? 'Alex Morgan' : 'Operator');
            final emailAndId = user != null
                ? '${user.email} · ID: ${user.id.length >= 8 ? user.id.substring(0, 8).toUpperCase() : user.id}'
                : (isMock
                      ? 'alex.morgan@example.com · ID: BM-9042'
                      : 'Not signed in');

            final userReports = ReportRepository.instance.userReports;
            final resolvedReportsCount = userReports
                .where(
                  (r) =>
                      r.backendStatus?.toUpperCase() == 'RESOLVED' ||
                      r.backendStatus?.toUpperCase() == 'CLOSED',
                )
                .length;
            final missingReportsCount = userReports
                .where(
                  (r) =>
                      r.status == ReportStatus.missing &&
                      r.backendStatus?.toUpperCase() != 'RESOLVED' &&
                      r.backendStatus?.toUpperCase() != 'CLOSED',
                )
                .length;
            final reportsSubtitle = userReports.isEmpty
                ? '0 reports'
                : (resolvedReportsCount > 0
                      ? '${userReports.length} ${userReports.length == 1 ? 'report' : 'reports'} ($missingReportsCount active missing, $resolvedReportsCount resolved)'
                      : '${userReports.length} ${userReports.length == 1 ? 'report' : 'reports'} ($missingReportsCount active missing)');

            final receivedCount =
                RecoveryRepository.instance.receivedRequests.length;
            final sentCount = RecoveryRepository.instance.sentRequests.length;
            final requestsSubtitle = (receivedCount == 0 && sentCount == 0)
                ? '0 requests'
                : '$receivedCount received, $sentCount sent';

            return SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // User Header Card
                  Container(
                    padding: const EdgeInsets.all(16),
                    decoration: BoxDecoration(
                      color: AppTheme.card,
                      borderRadius: BorderRadius.circular(
                        AppTheme.defaultRadius,
                      ),
                      border: Border.all(color: AppTheme.borderSubtle),
                    ),
                    child: Row(
                      children: [
                        Container(
                          width: 56,
                          height: 56,
                          decoration: BoxDecoration(
                            color: AppTheme.elevatedSurface,
                            shape: BoxShape.circle,
                            border: Border.all(color: AppTheme.borderMuted),
                          ),
                          alignment: Alignment.center,
                          child: Text(
                            initials,
                            style: const TextStyle(
                              fontSize: 20,
                              fontWeight: FontWeight.bold,
                              color: AppTheme.primaryText,
                            ),
                          ),
                        ),
                        const SizedBox(width: 14),
                        Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Row(
                                children: [
                                  Flexible(
                                    child: Text(
                                      name,
                                      style: Theme.of(context)
                                          .textTheme
                                          .titleLarge
                                          ?.copyWith(
                                            fontFamily: 'Hanken Grotesk',
                                            fontWeight: FontWeight.bold,
                                            color: AppTheme.primaryText,
                                          ),
                                      maxLines: 1,
                                      overflow: TextOverflow.ellipsis,
                                    ),
                                  ),
                                  if (user != null || isMock) ...[
                                    const SizedBox(width: 6),
                                    Container(
                                      padding: const EdgeInsets.symmetric(
                                        horizontal: 6,
                                        vertical: 2,
                                      ),
                                      decoration: BoxDecoration(
                                        color: AppTheme.elevatedSurface,
                                        borderRadius: BorderRadius.circular(
                                          AppTheme.smallRadius,
                                        ),
                                        border: Border.all(
                                          color: AppTheme.borderSubtle,
                                        ),
                                      ),
                                      child: const Text(
                                        'VERIFIED MEMBER',
                                        style: TextStyle(
                                          fontSize: 9,
                                          fontWeight: FontWeight.bold,
                                          color: AppTheme.primaryText,
                                          letterSpacing: 0.5,
                                        ),
                                      ),
                                    ),
                                  ],
                                ],
                              ),
                              const SizedBox(height: 3),
                              Text(
                                emailAndId,
                                style: const TextStyle(
                                  color: AppTheme.secondaryText,
                                  fontSize: 12,
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
                  const SizedBox(height: 20),

                  // Group 1: Operational Summary
                  const Padding(
                    padding: EdgeInsets.symmetric(horizontal: 4, vertical: 4),
                    child: Text(
                      'OPERATIONAL SUMMARY',
                      style: TextStyle(
                        color: AppTheme.secondaryText,
                        fontSize: 11,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 0.8,
                      ),
                    ),
                  ),
                  const SizedBox(height: 6),
                  Container(
                    decoration: BoxDecoration(
                      color: AppTheme.card,
                      borderRadius: BorderRadius.circular(
                        AppTheme.defaultRadius,
                      ),
                      border: Border.all(color: AppTheme.borderSubtle),
                    ),
                    child: Column(
                      children: [
                        // My Reports Row
                        InkWell(
                          onTap: () {
                            if (widget.onNavigateTab != null) {
                              widget.onNavigateTab!(3);
                            } else {
                              Navigator.push(
                                context,
                                MaterialPageRoute(
                                  builder: (_) => const MyReportsScreen(),
                                ),
                              );
                            }
                          },
                          borderRadius: const BorderRadius.vertical(
                            top: Radius.circular(AppTheme.defaultRadius),
                          ),
                          child: Padding(
                            padding: const EdgeInsets.all(14),
                            child: Row(
                              children: [
                                Container(
                                  width: 36,
                                  height: 36,
                                  decoration: BoxDecoration(
                                    color: AppTheme.surface,
                                    borderRadius: BorderRadius.circular(
                                      AppTheme.smallRadius,
                                    ),
                                    border: Border.all(
                                      color: AppTheme.borderSubtle,
                                    ),
                                  ),
                                  child: const Icon(
                                    Icons.inventory_2_outlined,
                                    size: 18,
                                    color: AppTheme.primaryText,
                                  ),
                                ),
                                const SizedBox(width: 12),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        'My Reports',
                                        style: TextStyle(
                                          fontWeight: FontWeight.bold,
                                          fontSize: 13,
                                          color: AppTheme.primaryText,
                                        ),
                                      ),
                                      const SizedBox(height: 2),
                                      Text(
                                        reportsSubtitle,
                                        style: const TextStyle(
                                          fontSize: 11,
                                          color: AppTheme.secondaryText,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                                const Icon(
                                  Icons.chevron_right,
                                  size: 18,
                                  color: AppTheme.secondaryText,
                                ),
                              ],
                            ),
                          ),
                        ),
                        const Divider(color: AppTheme.borderSubtle, height: 1),

                        // Dedicated Browse All Incident Reports Action (Required for test finder)
                        Padding(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 14,
                            vertical: 10,
                          ),
                          child: SizedBox(
                            width: double.infinity,
                            child: OutlinedButton(
                              onPressed: () {
                                if (widget.onNavigateTab != null) {
                                  widget.onNavigateTab!(3);
                                } else {
                                  Navigator.push(
                                    context,
                                    MaterialPageRoute(
                                      builder: (_) => const MyReportsScreen(),
                                    ),
                                  );
                                }
                              },
                              style: OutlinedButton.styleFrom(
                                side: const BorderSide(
                                  color: AppTheme.borderSubtle,
                                ),
                                padding: const EdgeInsets.symmetric(
                                  vertical: 10,
                                ),
                                shape: RoundedRectangleBorder(
                                  borderRadius: BorderRadius.circular(
                                    AppTheme.smallRadius,
                                  ),
                                ),
                              ),
                              child: const Text(
                                'Browse All Incident Reports',
                                style: TextStyle(
                                  fontSize: 12,
                                  fontWeight: FontWeight.w600,
                                  color: AppTheme.primaryText,
                                ),
                              ),
                            ),
                          ),
                        ),
                        const Divider(color: AppTheme.borderSubtle, height: 1),

                        // Recovery Requests Row
                        InkWell(
                          onTap: () {
                            Navigator.push(
                              context,
                              MaterialPageRoute(
                                builder: (_) => const RecoveryRequestsScreen(),
                              ),
                            );
                          },
                          borderRadius: const BorderRadius.vertical(
                            bottom: Radius.circular(AppTheme.defaultRadius),
                          ),
                          child: Padding(
                            padding: const EdgeInsets.all(14),
                            child: Row(
                              children: [
                                Container(
                                  width: 36,
                                  height: 36,
                                  decoration: BoxDecoration(
                                    color: AppTheme.surface,
                                    borderRadius: BorderRadius.circular(
                                      AppTheme.smallRadius,
                                    ),
                                    border: Border.all(
                                      color: AppTheme.borderSubtle,
                                    ),
                                  ),
                                  child: const Icon(
                                    Icons.swap_horiz,
                                    size: 18,
                                    color: AppTheme.primaryText,
                                  ),
                                ),
                                const SizedBox(width: 12),
                                Expanded(
                                  child: Column(
                                    crossAxisAlignment:
                                        CrossAxisAlignment.start,
                                    children: [
                                      Text(
                                        'Recovery Requests',
                                        style: TextStyle(
                                          fontWeight: FontWeight.bold,
                                          fontSize: 13,
                                          color: AppTheme.primaryText,
                                        ),
                                      ),
                                      const SizedBox(height: 2),
                                      Text(
                                        requestsSubtitle,
                                        style: const TextStyle(
                                          fontSize: 11,
                                          color: AppTheme.secondaryText,
                                        ),
                                      ),
                                    ],
                                  ),
                                ),
                                const Icon(
                                  Icons.chevron_right,
                                  size: 18,
                                  color: AppTheme.secondaryText,
                                ),
                              ],
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),

                  // Group 2: Preferences
                  const Padding(
                    padding: EdgeInsets.symmetric(horizontal: 4, vertical: 4),
                    child: Text(
                      'PREFERENCES',
                      style: TextStyle(
                        color: AppTheme.secondaryText,
                        fontSize: 11,
                        fontWeight: FontWeight.bold,
                        letterSpacing: 0.8,
                      ),
                    ),
                  ),
                  const SizedBox(height: 6),
                  Container(
                    decoration: BoxDecoration(
                      color: AppTheme.card,
                      borderRadius: BorderRadius.circular(
                        AppTheme.defaultRadius,
                      ),
                      border: Border.all(color: AppTheme.borderSubtle),
                    ),
                    child: Column(
                      children: [
                        _buildSettingsRow(
                          icon: Icons.tune,
                          title: 'Preferences & Settings',
                          subtitle: 'Configure alerts and notifications',
                          onTap: () {
                            Navigator.push(
                              context,
                              MaterialPageRoute(
                                builder: (_) => const SettingsScreen(),
                              ),
                            );
                          },
                        ),
                        const Divider(color: AppTheme.borderSubtle, height: 1),
                        _buildSettingsRow(
                          icon: Icons.shield_outlined,
                          title: 'Privacy & Security',
                          subtitle: 'Account authentication controls',
                          onTap: () {
                            AppToast.info(
                              context,
                              message: 'Privacy settings are configured.',
                            );
                          },
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 24),

                  // Group 3: Session Termination
                  Semantics(
                    button: true,
                    label: 'Terminate session and log out',
                    child: Tooltip(
                      message: 'Log Out',
                      child: SizedBox(
                        width: double.infinity,
                        child: OutlinedButton(
                          onPressed: () => _showLogoutDialog(context),
                          style: OutlinedButton.styleFrom(
                            side: const BorderSide(
                              color: AppTheme.borderSubtle,
                            ),
                            padding: const EdgeInsets.symmetric(vertical: 14),
                            shape: RoundedRectangleBorder(
                              borderRadius: BorderRadius.circular(
                                AppTheme.defaultRadius,
                              ),
                            ),
                          ),
                          child: const Text(
                            'Terminate & Log Out',
                            style: TextStyle(
                              color: AppTheme.primaryText,
                              fontWeight: FontWeight.bold,
                              fontSize: 13,
                            ),
                          ),
                        ),
                      ),
                    ),
                  ),
                  const SizedBox(height: 24),
                ],
              ),
            );
          },
        ),
      ),
    );
  }

  Widget _buildSettingsRow({
    required IconData icon,
    required String title,
    required String subtitle,
    required VoidCallback onTap,
  }) {
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.all(14),
        child: Row(
          children: [
            Container(
              width: 36,
              height: 36,
              decoration: BoxDecoration(
                color: AppTheme.surface,
                borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                border: Border.all(color: AppTheme.borderSubtle),
              ),
              child: Icon(icon, size: 18, color: AppTheme.primaryText),
            ),
            const SizedBox(width: 12),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: const TextStyle(
                      fontWeight: FontWeight.bold,
                      fontSize: 13,
                      color: AppTheme.primaryText,
                    ),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    subtitle,
                    style: const TextStyle(
                      fontSize: 11,
                      color: AppTheme.secondaryText,
                    ),
                  ),
                ],
              ),
            ),
            const Icon(
              Icons.chevron_right,
              size: 18,
              color: AppTheme.secondaryText,
            ),
          ],
        ),
      ),
    );
  }
}
