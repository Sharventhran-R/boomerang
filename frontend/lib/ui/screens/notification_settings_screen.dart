import 'package:flutter/material.dart';
import '../../models/notification_model.dart';
import '../../services/notification_repository.dart';
import '../../theme.dart';
import '../widgets/app_toast.dart';

/// Screen allowing the user to configure notification delivery channels,
/// event subscriptions, match score thresholds, and quiet hours.
class NotificationSettingsScreen extends StatefulWidget {
  const NotificationSettingsScreen({super.key});

  @override
  State<NotificationSettingsScreen> createState() =>
      _NotificationSettingsScreenState();
}

class _NotificationSettingsScreenState
    extends State<NotificationSettingsScreen> {
  bool _isLoading = true;
  bool _isSaving = false;

  bool _pushEnabled = true;
  bool _inAppEnabled = true;
  bool _matchAlertsEnabled = true;
  double _matchMinScore = 75.0;
  bool _matchHighPriorityOnly = false;
  bool _recoveryUpdatesEnabled = true;
  bool _reportStatusEnabled = true;
  bool _quietHoursEnabled = false;
  String _quietHoursStart = '22:00';
  String _quietHoursEnd = '08:00';

  @override
  void initState() {
    super.initState();
    _loadPreferences();
  }

  Future<void> _loadPreferences() async {
    final prefs = await NotificationRepository.instance.fetchPreferences();
    if (mounted) {
      setState(() {
        _pushEnabled = prefs.pushEnabled;
        _inAppEnabled = prefs.inAppEnabled;
        _matchAlertsEnabled = prefs.matchAlertsEnabled;
        _matchMinScore = prefs.matchMinScore.clamp(0.0, 100.0);
        _matchHighPriorityOnly = prefs.matchHighPriorityOnly;
        _recoveryUpdatesEnabled = prefs.recoveryUpdatesEnabled;
        _reportStatusEnabled = prefs.reportStatusEnabled;
        _quietHoursEnabled = prefs.quietHoursEnabled;
        _quietHoursStart = prefs.quietHoursStart ?? '22:00';
        _quietHoursEnd = prefs.quietHoursEnd ?? '08:00';
        _isLoading = false;
      });
    }
  }

  Future<void> _savePreferences() async {
    setState(() => _isSaving = true);

    try {
      final req = UpdateNotificationPreferenceRequest(
        pushEnabled: _pushEnabled,
        inAppEnabled: _inAppEnabled,
        matchAlertsEnabled: _matchAlertsEnabled,
        matchMinScore: _matchMinScore,
        matchHighPriorityOnly: _matchHighPriorityOnly,
        recoveryUpdatesEnabled: _recoveryUpdatesEnabled,
        reportStatusEnabled: _reportStatusEnabled,
        quietHoursEnabled: _quietHoursEnabled,
        quietHoursStart: _quietHoursEnabled ? _quietHoursStart : null,
        quietHoursEnd: _quietHoursEnabled ? _quietHoursEnd : null,
      );

      await NotificationRepository.instance.updatePreferences(req);

      if (mounted) {
        AppToast.success(context, message: 'Notification preferences saved');
      }
    } catch (e) {
      if (mounted) {
        AppToast.error(
          context,
          message: 'Failed to save preferences: ${e.toString()}',
        );
      }
    } finally {
      if (mounted) {
        setState(() => _isSaving = false);
      }
    }
  }

  Future<void> _pickTime({required bool isStart}) async {
    final currentStr = isStart ? _quietHoursStart : _quietHoursEnd;
    final parts = currentStr.split(':');
    final initialHour = int.tryParse(parts[0]) ?? (isStart ? 22 : 8);
    final initialMinute = parts.length > 1 ? (int.tryParse(parts[1]) ?? 0) : 0;

    final picked = await showTimePicker(
      context: context,
      initialTime: TimeOfDay(hour: initialHour, minute: initialMinute),
      builder: (context, child) {
        return Theme(
          data: Theme.of(context).copyWith(
            timePickerTheme: TimePickerThemeData(
              backgroundColor: AppTheme.card,
              hourMinuteColor: AppTheme.surface,
              hourMinuteTextColor: AppTheme.primaryText,
              dialHandColor: AppTheme.actionPrimary,
              dialBackgroundColor: AppTheme.surface,
              dialTextColor: AppTheme.primaryText,
              entryModeIconColor: AppTheme.primaryText,
            ),
          ),
          child: child ?? const SizedBox(),
        );
      },
    );

    if (picked != null && mounted) {
      final formatted =
          '${picked.hour.toString().padLeft(2, '0')}:${picked.minute.toString().padLeft(2, '0')}';
      setState(() {
        if (isStart) {
          _quietHoursStart = formatted;
        } else {
          _quietHoursEnd = formatted;
        }
      });
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        backgroundColor: AppTheme.surface,
        elevation: 0,
        title: const Text(
          'Notification Settings',
          style: TextStyle(
            fontFamily: 'Hanken Grotesk',
            fontSize: 16,
            fontWeight: FontWeight.bold,
            color: AppTheme.primaryText,
          ),
        ),
      ),
      body: _isLoading
          ? const Center(
              child: CircularProgressIndicator(
                strokeWidth: 2,
                color: AppTheme.actionPrimary,
              ),
            )
          : SafeArea(
              child: SingleChildScrollView(
                padding: const EdgeInsets.all(16),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.stretch,
                  children: [
                    // Section 1: DELIVERY CHANNELS
                    _buildSectionHeader('DELIVERY CHANNELS'),
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
                          _buildSwitchTile(
                            title: 'Push Notifications',
                            subtitle:
                                'Receive real-time system alerts on this device',
                            value: _pushEnabled,
                            onChanged: (v) => setState(() => _pushEnabled = v),
                          ),
                          const Divider(
                            color: AppTheme.borderSubtle,
                            height: 1,
                          ),
                          _buildSwitchTile(
                            title: 'In-App Notifications',
                            subtitle:
                                'Display notification center badges and history',
                            value: _inAppEnabled,
                            onChanged: (v) => setState(() => _inAppEnabled = v),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 24),

                    // Section 2: EVENT ALERTS
                    _buildSectionHeader('EVENT SUBSCRIPTIONS'),
                    Container(
                      decoration: BoxDecoration(
                        color: AppTheme.card,
                        borderRadius: BorderRadius.circular(
                          AppTheme.defaultRadius,
                        ),
                        border: Border.all(color: AppTheme.borderSubtle),
                      ),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          _buildSwitchTile(
                            title: 'Match Alerts',
                            subtitle:
                                'Alert when high-probability item matches occur',
                            value: _matchAlertsEnabled,
                            onChanged: (v) =>
                                setState(() => _matchAlertsEnabled = v),
                          ),
                          if (_matchAlertsEnabled) ...[
                            const Divider(
                              color: AppTheme.borderSubtle,
                              height: 1,
                            ),
                            Padding(
                              padding: const EdgeInsets.fromLTRB(16, 14, 16, 8),
                              child: Column(
                                crossAxisAlignment: CrossAxisAlignment.start,
                                children: [
                                  Row(
                                    mainAxisAlignment:
                                        MainAxisAlignment.spaceBetween,
                                    children: [
                                      const Text(
                                        'Minimum Match Score',
                                        style: TextStyle(
                                          fontSize: 13,
                                          fontWeight: FontWeight.w600,
                                          color: AppTheme.primaryText,
                                        ),
                                      ),
                                      Text(
                                        '${_matchMinScore.toInt()}%',
                                        style: const TextStyle(
                                          fontFamily: 'Hanken Grotesk',
                                          fontSize: 14,
                                          fontWeight: FontWeight.bold,
                                          color: AppTheme.actionPrimary,
                                        ),
                                      ),
                                    ],
                                  ),
                                  const SizedBox(height: 4),
                                  const Text(
                                    'Suppress alerts below this confidence threshold',
                                    style: TextStyle(
                                      fontSize: 11,
                                      color: AppTheme.secondaryText,
                                    ),
                                  ),
                                  SliderTheme(
                                    data: SliderTheme.of(context).copyWith(
                                      activeTrackColor: AppTheme.actionPrimary,
                                      inactiveTrackColor: AppTheme.borderSubtle,
                                      thumbColor: AppTheme.actionPrimary,
                                      overlayColor: AppTheme.actionPrimary
                                          .withValues(alpha: 0.2),
                                    ),
                                    child: Slider(
                                      value: _matchMinScore,
                                      min: 0,
                                      max: 100,
                                      divisions: 20,
                                      label: '${_matchMinScore.toInt()}%',
                                      onChanged: (val) {
                                        setState(() => _matchMinScore = val);
                                      },
                                    ),
                                  ),
                                ],
                              ),
                            ),
                            const Divider(
                              color: AppTheme.borderSubtle,
                              height: 1,
                            ),
                            _buildSwitchTile(
                              title: 'High Priority Only',
                              subtitle:
                                  'Only trigger alerts meeting high-priority criteria',
                              value: _matchHighPriorityOnly,
                              onChanged: (v) =>
                                  setState(() => _matchHighPriorityOnly = v),
                            ),
                          ],
                          const Divider(
                            color: AppTheme.borderSubtle,
                            height: 1,
                          ),
                          _buildSwitchTile(
                            title: 'Recovery Request Updates',
                            subtitle:
                                'Notifications about ownership claims and handoffs',
                            value: _recoveryUpdatesEnabled,
                            onChanged: (v) =>
                                setState(() => _recoveryUpdatesEnabled = v),
                          ),
                          const Divider(
                            color: AppTheme.borderSubtle,
                            height: 1,
                          ),
                          _buildSwitchTile(
                            title: 'Report Status Updates',
                            subtitle:
                                'Alerts when your incident reports change state',
                            value: _reportStatusEnabled,
                            onChanged: (v) =>
                                setState(() => _reportStatusEnabled = v),
                          ),
                        ],
                      ),
                    ),
                    const SizedBox(height: 24),

                    // Section 3: QUIET HOURS
                    _buildSectionHeader('QUIET HOURS'),
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
                          _buildSwitchTile(
                            title: 'Enable Quiet Hours',
                            subtitle:
                                'Postpone push notifications during night hours',
                            value: _quietHoursEnabled,
                            onChanged: (v) =>
                                setState(() => _quietHoursEnabled = v),
                          ),
                          if (_quietHoursEnabled) ...[
                            const Divider(
                              color: AppTheme.borderSubtle,
                              height: 1,
                            ),
                            _buildTimeRow(
                              title: 'Quiet Hours Start',
                              timeStr: _quietHoursStart,
                              onTap: () => _pickTime(isStart: true),
                            ),
                            const Divider(
                              color: AppTheme.borderSubtle,
                              height: 1,
                            ),
                            _buildTimeRow(
                              title: 'Quiet Hours End',
                              timeStr: _quietHoursEnd,
                              onTap: () => _pickTime(isStart: false),
                            ),
                          ],
                        ],
                      ),
                    ),
                    const SizedBox(height: 32),

                    // Save Button
                    SizedBox(
                      height: 48,
                      child: ElevatedButton(
                        onPressed: _isSaving ? null : _savePreferences,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppTheme.actionPrimary,
                          foregroundColor: AppTheme.onActionPrimary,
                          disabledBackgroundColor: AppTheme.actionPrimary
                              .withValues(alpha: 0.5),
                          shape: RoundedRectangleBorder(
                            borderRadius: BorderRadius.circular(
                              AppTheme.smallRadius,
                            ),
                          ),
                        ),
                        child: _isSaving
                            ? const SizedBox(
                                width: 20,
                                height: 20,
                                child: CircularProgressIndicator(
                                  strokeWidth: 2,
                                  color: AppTheme.onActionPrimary,
                                ),
                              )
                            : const Text(
                                'Save Preferences',
                                style: TextStyle(
                                  fontWeight: FontWeight.bold,
                                  fontSize: 14,
                                ),
                              ),
                      ),
                    ),
                  ],
                ),
              ),
            ),
    );
  }

  Widget _buildSectionHeader(String title) {
    return Padding(
      padding: const EdgeInsets.symmetric(horizontal: 4, vertical: 8),
      child: Text(
        title,
        style: const TextStyle(
          color: AppTheme.secondaryText,
          fontSize: 11,
          fontWeight: FontWeight.bold,
          letterSpacing: 0.8,
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
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 12),
      child: Row(
        children: [
          Expanded(
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Text(
                  title,
                  style: const TextStyle(
                    fontSize: 13,
                    fontWeight: FontWeight.w600,
                    color: AppTheme.primaryText,
                  ),
                ),
                const SizedBox(height: 2),
                Text(
                  subtitle,
                  style: const TextStyle(
                    fontSize: 11.5,
                    color: AppTheme.secondaryText,
                  ),
                ),
              ],
            ),
          ),
          Switch.adaptive(
            value: value,
            activeThumbColor: AppTheme.actionPrimary,
            activeTrackColor: AppTheme.elevatedSurface,
            inactiveThumbColor: AppTheme.secondaryText,
            inactiveTrackColor: AppTheme.surface,
            onChanged: onChanged,
          ),
        ],
      ),
    );
  }

  Widget _buildTimeRow({
    required String title,
    required String timeStr,
    required VoidCallback onTap,
  }) {
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 14),
        child: Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            Text(
              title,
              style: const TextStyle(
                fontSize: 13,
                fontWeight: FontWeight.w500,
                color: AppTheme.primaryText,
              ),
            ),
            Row(
              children: [
                Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: AppTheme.surface,
                    borderRadius: BorderRadius.circular(AppTheme.smallRadius),
                    border: Border.all(color: AppTheme.borderSubtle),
                  ),
                  child: Text(
                    timeStr,
                    style: const TextStyle(
                      fontFamily: 'Hanken Grotesk',
                      fontSize: 13,
                      fontWeight: FontWeight.bold,
                      color: AppTheme.primaryText,
                    ),
                  ),
                ),
                const SizedBox(width: 8),
                const Icon(
                  Icons.access_time,
                  size: 16,
                  color: AppTheme.secondaryText,
                ),
              ],
            ),
          ],
        ),
      ),
    );
  }
}
