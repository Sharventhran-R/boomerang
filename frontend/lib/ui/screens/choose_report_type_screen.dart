import 'package:flutter/material.dart';
import '../../theme.dart';
import '../widgets/status_label.dart';
import 'create_report_screen.dart';

class ChooseReportTypeScreen extends StatelessWidget {
  final String? initialType;
  final VoidCallback? onClose;

  const ChooseReportTypeScreen({super.key, this.initialType, this.onClose});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.background,
      appBar: AppBar(
        backgroundColor: AppTheme.card,
        elevation: 0,
        title: const Text(
          'Choose Report Type',
          style: TextStyle(
            color: AppTheme.primaryText,
            fontWeight: FontWeight.w600,
            fontSize: 16,
          ),
        ),
        leading: Tooltip(
          message: 'Back',
          child: IconButton(
            icon: const Icon(Icons.arrow_back, color: AppTheme.primaryText),
            tooltip: 'Back',
            onPressed: () {
              if (onClose != null) {
                onClose!();
              } else if (Navigator.of(context).canPop()) {
                Navigator.of(context).pop();
              }
            },
          ),
        ),
      ),
      body: SafeArea(
        child: SingleChildScrollView(
          padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 20),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.stretch,
            children: [
              // Step indicator
              Align(
                alignment: Alignment.centerLeft,
                child: Container(
                  padding: const EdgeInsets.symmetric(
                    horizontal: 10,
                    vertical: 4,
                  ),
                  decoration: BoxDecoration(
                    color: AppTheme.card,
                    borderRadius: BorderRadius.circular(AppTheme.smallRadius),
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
                      const SizedBox(width: 8),
                      const Text(
                        'STEP 1 OF 3',
                        style: TextStyle(
                          fontSize: 10,
                          fontWeight: FontWeight.bold,
                          color: AppTheme.secondaryText,
                          letterSpacing: 1.0,
                        ),
                      ),
                    ],
                  ),
                ),
              ),
              const SizedBox(height: 16),

              const Text(
                'What would you like to report?',
                style: TextStyle(
                  fontFamily: 'Hanken Grotesk',
                  color: AppTheme.primaryText,
                  fontSize: 24,
                  fontWeight: FontWeight.bold,
                  letterSpacing: -0.5,
                ),
              ),
              const SizedBox(height: 6),
              const Text(
                'Select an option below to create an item report and alert community members in your area.',
                style: TextStyle(
                  color: AppTheme.secondaryText,
                  fontSize: 13,
                  height: 1.4,
                ),
              ),
              const SizedBox(height: 24),

              // Option 1: Missing
              _buildTypeCard(
                context,
                title: 'Report Something Missing',
                subtitle:
                    'Broadcast an alert for your lost item. Attach photos, last-seen location, and an optional reward for recovery.',
                status: ReportStatus.missing,
                icon: Icons.search,
                isHighlighted: initialType == 'missing',
                onTap: () async {
                  final result = await Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (_) => const CreateReportScreen(
                        initialStatus: ReportStatus.missing,
                      ),
                    ),
                  );
                  if (result == true && context.mounted) {
                    if (onClose != null) {
                      onClose!();
                    } else if (Navigator.of(context).canPop()) {
                      Navigator.of(context).pop(true);
                    }
                  }
                },
              ),
              const SizedBox(height: 16),

              // Option 2: Found
              _buildTypeCard(
                context,
                title: 'Report Something Found',
                subtitle:
                    'Register an item you located. Boomerang matches it against open missing reports and notifies verified owners.',
                status: ReportStatus.found,
                icon: Icons.volunteer_activism,
                isHighlighted: initialType == 'found',
                onTap: () async {
                  final result = await Navigator.push(
                    context,
                    MaterialPageRoute(
                      builder: (_) => const CreateReportScreen(
                        initialStatus: ReportStatus.found,
                      ),
                    ),
                  );
                  if (result == true && context.mounted) {
                    if (onClose != null) {
                      onClose!();
                    } else if (Navigator.of(context).canPop()) {
                      Navigator.of(context).pop(true);
                    }
                  }
                },
              ),
              const SizedBox(height: 24),

              // Info Banner
              Container(
                padding: const EdgeInsets.all(14),
                decoration: BoxDecoration(
                  color: AppTheme.card,
                  borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
                  border: Border.all(color: AppTheme.borderSubtle),
                ),
                child: const Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Icon(
                      Icons.shield_outlined,
                      size: 18,
                      color: AppTheme.secondaryText,
                    ),
                    SizedBox(width: 12),
                    Expanded(
                      child: Text(
                        'Reports are publicly discoverable only within a specified geographic radius. Private contact coordinates remain protected.',
                        style: TextStyle(
                          color: AppTheme.secondaryText,
                          fontSize: 12,
                          height: 1.4,
                        ),
                      ),
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

  Widget _buildTypeCard(
    BuildContext context, {
    required String title,
    required String subtitle,
    required ReportStatus status,
    required IconData icon,
    required bool isHighlighted,
    required VoidCallback onTap,
  }) {
    final statusText = status == ReportStatus.missing ? 'MISSING' : 'FOUND';
    return Semantics(
      button: true,
      label: '$statusText: $title. $subtitle. Continue to Step 2',
      child: Tooltip(
        message: title,
        child: InkWell(
          onTap: onTap,
          borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
          child: Container(
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
              color: isHighlighted ? AppTheme.elevatedSurface : AppTheme.card,
              borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
              border: Border.all(
                color: isHighlighted
                    ? AppTheme.actionPrimary
                    : AppTheme.borderSubtle,
                width: isHighlighted ? 1.5 : 1.0,
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    StatusLabel(status: status),
                    Container(
                      width: 36,
                      height: 36,
                      decoration: BoxDecoration(
                        color: AppTheme.surface,
                        borderRadius: BorderRadius.circular(
                          AppTheme.smallRadius,
                        ),
                        border: Border.all(color: AppTheme.borderSubtle),
                      ),
                      child: Icon(icon, color: AppTheme.primaryText, size: 20),
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                Text(
                  title,
                  style: const TextStyle(
                    fontFamily: 'Hanken Grotesk',
                    fontSize: 17,
                    fontWeight: FontWeight.bold,
                    color: AppTheme.primaryText,
                  ),
                ),
                const SizedBox(height: 6),
                Text(
                  subtitle,
                  style: const TextStyle(
                    fontSize: 13,
                    color: AppTheme.secondaryText,
                    height: 1.4,
                  ),
                ),
                const SizedBox(height: 14),
                Row(
                  children: [
                    Text(
                      'Select & Configure Step 2',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w600,
                        color: isHighlighted
                            ? AppTheme.primaryText
                            : AppTheme.secondaryText,
                      ),
                    ),
                    const SizedBox(width: 4),
                    Icon(
                      Icons.arrow_forward,
                      size: 14,
                      color: isHighlighted
                          ? AppTheme.primaryText
                          : AppTheme.secondaryText,
                    ),
                  ],
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
