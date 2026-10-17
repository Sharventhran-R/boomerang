import 'package:flutter/material.dart';
import '../../theme.dart';
import '../widgets/app_toast.dart';

class SettingsScreen extends StatefulWidget {
  const SettingsScreen({super.key});

  @override
  State<SettingsScreen> createState() => _SettingsScreenState();
}

class _SettingsScreenState extends State<SettingsScreen> {
  bool _emailNotifications = true;
  bool _proximityAlerts = true;
  bool _marketing = false;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        backgroundColor: AppTheme.card,
        elevation: 0,
        title: const Text(
          'System Preferences',
          style: TextStyle(
            color: AppTheme.primaryText,
            fontWeight: FontWeight.w600,
            fontSize: 16,
          ),
        ),
        iconTheme: const IconThemeData(color: AppTheme.primaryText),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 16),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Header title
              Text(
                'System Preferences',
                style: Theme.of(context).textTheme.headlineSmall?.copyWith(
                  fontFamily: 'Hanken Grotesk',
                  color: AppTheme.primaryText,
                  fontWeight: FontWeight.bold,
                  letterSpacing: -0.3,
                ),
              ),
              const SizedBox(height: 4),
              const Text(
                'Manage alerts, proximity preferences, and storage settings.',
                style: TextStyle(color: AppTheme.secondaryText, fontSize: 13),
              ),
              const SizedBox(height: 20),

              // Group 1: Notifications
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: 4, vertical: 4),
                child: Text(
                  'NOTIFICATIONS',
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
                  borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
                  border: Border.all(color: AppTheme.borderSubtle),
                ),
                child: Column(
                  children: [
                    _buildSwitchTile(
                      title: 'Email Notifications for Recovery Requests',
                      subtitle:
                          'Get email alerts when an item match is reported.',
                      value: _emailNotifications,
                      onChanged: (v) => setState(() => _emailNotifications = v),
                    ),
                    const Divider(color: AppTheme.borderSubtle, height: 1),
                    _buildSwitchTile(
                      title: 'Proximity Alerts (Radius ≤ 2.0 km)',
                      subtitle:
                          'Notify me when missing items are reported nearby.',
                      value: _proximityAlerts,
                      onChanged: (v) => setState(() => _proximityAlerts = v),
                    ),
                    const Divider(color: AppTheme.borderSubtle, height: 1),
                    _buildSwitchTile(
                      title: 'Product Updates & Community Digests',
                      subtitle:
                          'Weekly summary of recovered items in your active area.',
                      value: _marketing,
                      onChanged: (v) => setState(() => _marketing = v),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 20),

              // Group 2: Privacy & Geolocation
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: 4, vertical: 4),
                child: Text(
                  'LOCATION & PRIVACY',
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
                  borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
                  border: Border.all(color: AppTheme.borderSubtle),
                ),
                child: Column(
                  children: [
                    ListTile(
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 4,
                      ),
                      leading: const Icon(
                        Icons.gps_fixed,
                        color: AppTheme.primaryText,
                        size: 20,
                      ),
                      title: const Text(
                        'Location Access: Enabled (High Precision)',
                        style: TextStyle(
                          color: AppTheme.primaryText,
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      subtitle: const Text(
                        'Accurate GPS used for radius searches.',
                        style: TextStyle(
                          color: AppTheme.secondaryText,
                          fontSize: 11,
                        ),
                      ),
                      trailing: const Icon(
                        Icons.check_circle,
                        color: AppTheme.primaryText,
                        size: 18,
                      ),
                    ),
                    const Divider(color: AppTheme.borderSubtle, height: 1),
                    ListTile(
                      contentPadding: const EdgeInsets.symmetric(
                        horizontal: 14,
                        vertical: 4,
                      ),
                      leading: const Icon(
                        Icons.visibility_off_outlined,
                        color: AppTheme.secondaryText,
                        size: 20,
                      ),
                      title: const Text(
                        'Reporter Contact Shield',
                        style: TextStyle(
                          color: AppTheme.primaryText,
                          fontSize: 13,
                          fontWeight: FontWeight.w600,
                        ),
                      ),
                      subtitle: const Text(
                        'Phone & email remain masked until mutual handover accept.',
                        style: TextStyle(
                          color: AppTheme.secondaryText,
                          fontSize: 11,
                        ),
                      ),
                      trailing: Container(
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
                        child: const Text(
                          'ACTIVE',
                          style: TextStyle(
                            fontSize: 10,
                            fontWeight: FontWeight.bold,
                            color: AppTheme.primaryText,
                          ),
                        ),
                      ),
                    ),
                  ],
                ),
              ),
              const SizedBox(height: 20),

              // Group 3: Data & Cache
              const Padding(
                padding: EdgeInsets.symmetric(horizontal: 4, vertical: 4),
                child: Text(
                  'DATA & STORAGE',
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
                  borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
                  border: Border.all(color: AppTheme.borderSubtle),
                ),
                child: ListTile(
                  contentPadding: const EdgeInsets.symmetric(
                    horizontal: 14,
                    vertical: 4,
                  ),
                  leading: const Icon(
                    Icons.cleaning_services_outlined,
                    color: AppTheme.secondaryText,
                    size: 20,
                  ),
                  title: const Text(
                    'Clear Map & Photo Cache',
                    style: TextStyle(
                      color: AppTheme.primaryText,
                      fontSize: 13,
                      fontWeight: FontWeight.w600,
                    ),
                  ),
                  subtitle: const Text(
                    'Free up local temporary media storage (2.4 MB).',
                    style: TextStyle(
                      color: AppTheme.secondaryText,
                      fontSize: 11,
                    ),
                  ),
                  trailing: TextButton(
                    onPressed: () {
                      AppToast.info(
                        context,
                        message: 'Offline image cache cleared.',
                      );
                    },
                    child: const Text(
                      'Clear',
                      style: TextStyle(
                        color: AppTheme.primaryText,
                        fontWeight: FontWeight.bold,
                        fontSize: 12,
                      ),
                    ),
                  ),
                ),
              ),
              const SizedBox(height: 30),
            ],
          ),
        ),
      ),
    );
  }

  Widget _buildSwitchTile({
    required String title,
    required String subtitle,
    required bool value,
    required ValueChanged<bool> onChanged,
  }) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 8),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    color: AppTheme.primaryText,
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  subtitle,
                  style: const TextStyle(
                    color: AppTheme.secondaryText,
                    fontSize: 11,
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(width: 10),
          Switch(
            value: value,
            onChanged: onChanged,
            activeThumbColor: AppTheme.actionPrimary,
            activeTrackColor: AppTheme.elevatedSurface,
            inactiveThumbColor: AppTheme.secondaryText,
            inactiveTrackColor: AppTheme.surface,
          ),
        ],
      ),
    );
  }
}
