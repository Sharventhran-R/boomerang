import 'package:flutter/material.dart';
import '../../services/auth_service.dart';
import '../../services/report_repository.dart';
import '../../theme.dart';
import 'choose_report_type_screen.dart';
import 'home_screen.dart';
import 'map_screen.dart';
import 'my_reports_screen.dart';
import 'profile_screen.dart';
import 'recovery_requests_screen.dart';
import 'settings_screen.dart';

class MainNavScreen extends StatefulWidget {
  const MainNavScreen({super.key});

  @override
  State<MainNavScreen> createState() => _MainNavScreenState();
}

class _MainNavScreenState extends State<MainNavScreen> {
  int _currentIndex = 0;
  String? _createInitialType;

  @override
  void initState() {
    super.initState();
    AuthService.instance.addListener(_onAuthChanged);
  }

  void _onAuthChanged() {
    if (mounted) setState(() {});
  }

  @override
  void dispose() {
    AuthService.instance.removeListener(_onAuthChanged);
    super.dispose();
  }

  List<Widget> _buildScreens() {
    return [
      HomeScreen(
        onNavigateTab: (index) => setState(() => _currentIndex = index),
        onInitiateCreate: (type) => setState(() {
          _createInitialType = type;
          _currentIndex = 2;
        }),
      ),
      MapScreen(
        onNavigateTab: (index) => setState(() => _currentIndex = index),
      ),
      ChooseReportTypeScreen(
        initialType: _createInitialType,
        onClose: () => setState(() => _currentIndex = 0),
      ),
      const MyReportsScreen(),
      ProfileScreen(
        onNavigateTab: (index) => setState(() => _currentIndex = index),
      ),
    ];
  }

  @override
  Widget build(BuildContext context) {
    final screens = _buildScreens();
    final isDesktop = MediaQuery.of(context).size.width >= 840;

    if (isDesktop) {
      return Scaffold(
        backgroundColor: AppTheme.background,
        body: Row(
          children: [
            // Desktop Sidebar Navigation (240px)
            Container(
              width: 240,
              decoration: const BoxDecoration(
                color: AppTheme.surface,
                border: Border(right: BorderSide(color: AppTheme.borderSubtle)),
              ),
              child: SafeArea(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // Brand Header
                    Padding(
                      padding: const EdgeInsets.fromLTRB(20, 20, 20, 16),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.start,
                        children: [
                          Row(
                            children: [
                              Container(
                                width: 28,
                                height: 28,
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
                                  Icons.cached,
                                  size: 16,
                                  color: AppTheme.primaryText,
                                ),
                              ),
                              const SizedBox(width: 10),
                              const Text(
                                'BOOMERANG',
                                style: TextStyle(
                                  fontFamily: 'Hanken Grotesk',
                                  fontSize: 16,
                                  fontWeight: FontWeight.bold,
                                  letterSpacing: 1.0,
                                  color: AppTheme.primaryText,
                                ),
                              ),
                            ],
                          ),
                          const SizedBox(height: 6),
                          const Text(
                            'LOST & FOUND NETWORK',
                            style: TextStyle(
                              fontSize: 9,
                              fontWeight: FontWeight.bold,
                              letterSpacing: 0.8,
                              color: AppTheme.mutedText,
                            ),
                          ),
                        ],
                      ),
                    ),
                    const Divider(color: AppTheme.borderSubtle, height: 1),

                    // Scrollable Nav Items
                    Expanded(
                      child: SingleChildScrollView(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.stretch,
                          children: [
                            // Navigation Section
                            Padding(
                              padding: const EdgeInsets.fromLTRB(20, 16, 20, 6),
                              child: const Text(
                                'NAVIGATION',
                                style: TextStyle(
                                  fontSize: 10,
                                  fontWeight: FontWeight.bold,
                                  letterSpacing: 1.0,
                                  color: AppTheme.secondaryText,
                                ),
                              ),
                            ),
                            _buildSidebarItem(0, Icons.grid_view, 'Home'),
                            _buildSidebarItem(1, Icons.map, 'Map'),
                            _buildSidebarItem(2, Icons.add_box, 'Create'),
                            _buildSidebarItem(3, Icons.inventory_2, 'Reports'),
                            _buildSidebarActionItem(
                              icon: Icons.swap_horiz,
                              label: 'Recovery Requests',
                              onTap: () {
                                Navigator.push(
                                  context,
                                  MaterialPageRoute(
                                    builder: (_) =>
                                        const RecoveryRequestsScreen(),
                                  ),
                                );
                              },
                            ),

                            const SizedBox(height: 12),
                            const Divider(
                              color: AppTheme.borderSubtle,
                              height: 1,
                            ),

                            // Preferences Section
                            Padding(
                              padding: const EdgeInsets.fromLTRB(20, 16, 20, 6),
                              child: const Text(
                                'PREFERENCES',
                                style: TextStyle(
                                  fontSize: 10,
                                  fontWeight: FontWeight.bold,
                                  letterSpacing: 1.0,
                                  color: AppTheme.secondaryText,
                                ),
                              ),
                            ),
                            _buildSidebarItem(4, Icons.person, 'Profile'),
                            _buildSidebarActionItem(
                              icon: Icons.settings,
                              label: 'Settings',
                              onTap: () {
                                Navigator.push(
                                  context,
                                  MaterialPageRoute(
                                    builder: (_) => const SettingsScreen(),
                                  ),
                                );
                              },
                            ),
                          ],
                        ),
                      ),
                    ),

                    const Divider(color: AppTheme.borderSubtle, height: 1),

                    // User Identity Unit
                    ListenableBuilder(
                      listenable: AuthService.instance,
                      builder: (context, _) {
                        final user = AuthService.instance.currentUser;
                        final isMock =
                            ReportRepository.instance.isMockMode &&
                            user == null;
                        final displayName =
                            (user != null && user.name.isNotEmpty)
                            ? user.name
                            : (isMock ? 'Alex Morgan' : 'Operator');
                        final displayInitials =
                            user?.initials ?? (isMock ? 'AM' : 'OP');
                        final displayRole =
                            (user != null && user.email.isNotEmpty)
                            ? user.email
                            : (isMock ? 'Member' : 'Not signed in');

                        return Semantics(
                          button: true,
                          label: '$displayName Profile. Tap to open profile',
                          child: Tooltip(
                            message: 'View Profile',
                            child: InkWell(
                              onTap: () => setState(() => _currentIndex = 4),
                              child: Padding(
                                padding: const EdgeInsets.all(16),
                                child: Container(
                                  padding: const EdgeInsets.all(12),
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
                                    children: [
                                      Container(
                                        width: 32,
                                        height: 32,
                                        decoration: BoxDecoration(
                                          color: AppTheme.elevatedSurface,
                                          borderRadius: BorderRadius.circular(
                                            AppTheme.smallRadius,
                                          ),
                                          border: Border.all(
                                            color: AppTheme.borderMuted,
                                          ),
                                        ),
                                        alignment: Alignment.center,
                                        child: Text(
                                          displayInitials,
                                          style: const TextStyle(
                                            fontSize: 11,
                                            fontWeight: FontWeight.bold,
                                            color: AppTheme.primaryText,
                                          ),
                                        ),
                                      ),
                                      const SizedBox(width: 10),
                                      Expanded(
                                        child: Column(
                                          crossAxisAlignment:
                                              CrossAxisAlignment.start,
                                          children: [
                                            Text(
                                              displayName,
                                              style: const TextStyle(
                                                fontSize: 12,
                                                fontWeight: FontWeight.bold,
                                                color: AppTheme.primaryText,
                                              ),
                                              overflow: TextOverflow.ellipsis,
                                            ),
                                            const SizedBox(height: 2),
                                            Text(
                                              displayRole,
                                              style: const TextStyle(
                                                fontSize: 10,
                                                color: AppTheme.mutedText,
                                              ),
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
                          ),
                        );
                      },
                    ),
                  ],
                ),
              ),
            ),

            // Main Body Canvas
            Expanded(child: screens[_currentIndex]),
          ],
        ),
      );
    }

    // Primary Mobile Viewport (~390x844)
    return Scaffold(
      backgroundColor: AppTheme.background,
      body: screens[_currentIndex],
      // No extendBody: true to ensure scrolling content is never obscured by the bottom navigation bar.
      extendBody: false,
      bottomNavigationBar: Container(
        decoration: const BoxDecoration(
          color: AppTheme.card,
          border: Border(
            top: BorderSide(color: AppTheme.borderSubtle, width: 0.5),
          ),
        ),
        child: SafeArea(
          child: SizedBox(
            height: 60,
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceAround,
              children: [
                _buildNavItem(0, Icons.explore_outlined, 'Home'),
                _buildNavItem(1, Icons.map_outlined, 'Map'),
                _buildCreateAction(),
                _buildNavItem(3, Icons.inventory_2_outlined, 'Reports'),
                _buildNavItem(4, Icons.person_outline, 'Profile'),
              ],
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildSidebarItem(int index, IconData icon, String label) {
    final isSelected = _currentIndex == index;
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 10, vertical: 2),
      decoration: BoxDecoration(
        color: isSelected ? AppTheme.elevatedSurface : Colors.transparent,
        borderRadius: BorderRadius.circular(AppTheme.smallRadius),
        border: isSelected ? Border.all(color: AppTheme.borderSubtle) : null,
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(AppTheme.smallRadius),
          onTap: () => setState(() => _currentIndex = index),
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            child: Row(
              children: [
                Icon(
                  icon,
                  size: 18,
                  color: isSelected
                      ? AppTheme.primaryText
                      : AppTheme.secondaryText,
                ),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    label,
                    overflow: TextOverflow.ellipsis,
                    style: TextStyle(
                      fontSize: 13,
                      fontWeight: isSelected
                          ? FontWeight.bold
                          : FontWeight.w500,
                      color: isSelected
                          ? AppTheme.primaryText
                          : AppTheme.secondaryText,
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

  Widget _buildSidebarActionItem({
    required IconData icon,
    required String label,
    required VoidCallback onTap,
  }) {
    return Container(
      margin: const EdgeInsets.symmetric(horizontal: 10, vertical: 2),
      decoration: BoxDecoration(
        color: Colors.transparent,
        borderRadius: BorderRadius.circular(AppTheme.smallRadius),
      ),
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          borderRadius: BorderRadius.circular(AppTheme.smallRadius),
          onTap: onTap,
          child: Padding(
            padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 10),
            child: Row(
              children: [
                Icon(icon, size: 18, color: AppTheme.secondaryText),
                const SizedBox(width: 12),
                Expanded(
                  child: Text(
                    label,
                    overflow: TextOverflow.ellipsis,
                    style: const TextStyle(
                      fontSize: 13,
                      fontWeight: FontWeight.w500,
                      color: AppTheme.secondaryText,
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

  Widget _buildNavItem(int index, IconData icon, String label) {
    final isSelected = _currentIndex == index;
    final color = isSelected ? AppTheme.primaryText : AppTheme.secondaryText;
    return Semantics(
      button: true,
      label: '$label navigation tab',
      selected: isSelected,
      child: Tooltip(
        message: label,
        child: InkWell(
          key: ValueKey('nav_tab_${label.toLowerCase()}'),
          onTap: () => setState(() => _currentIndex = index),
          borderRadius: BorderRadius.circular(AppTheme.smallRadius),
          child: ConstrainedBox(
            constraints: const BoxConstraints(minWidth: 54, minHeight: 48),
            child: Center(
              widthFactor: 1.0,
              heightFactor: 1.0,
              child: Column(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(icon, color: color, size: 21),
                  const SizedBox(height: 3),
                  Text(
                    label,
                    style: TextStyle(
                      color: color,
                      fontSize: 10,
                      fontWeight: isSelected
                          ? FontWeight.bold
                          : FontWeight.w500,
                      letterSpacing: 0.1,
                    ),
                  ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildCreateAction() {
    return Semantics(
      button: true,
      label: 'Create new report',
      child: Tooltip(
        message: 'Create Report',
        child: InkWell(
          onTap: () => setState(() {
            _createInitialType = null;
            _currentIndex = 2;
          }),
          borderRadius: BorderRadius.circular(AppTheme.smallRadius),
          child: ConstrainedBox(
            constraints: const BoxConstraints(minWidth: 52, minHeight: 48),
            child: Center(
              child: Container(
                width: 38,
                height: 38,
                decoration: BoxDecoration(
                  color: AppTheme.actionPrimary,
                  borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                  boxShadow: const [
                    BoxShadow(
                      color: Colors.black38,
                      blurRadius: 4,
                      offset: Offset(0, 2),
                    ),
                  ],
                ),
                child: const Icon(
                  Icons.add,
                  color: AppTheme.onActionPrimary,
                  size: 22,
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
