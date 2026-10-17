import 'package:flutter/material.dart';
import '../../theme.dart';

enum ReportStatus { missing, found }

class StatusLabel extends StatelessWidget {
  final ReportStatus status;

  const StatusLabel({super.key, required this.status});

  @override
  Widget build(BuildContext context) {
    final isMissing = status == ReportStatus.missing;

    // Strict Monochromatic distinction: High-contrast solid border vs muted tonal border
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2.5),
      decoration: BoxDecoration(
        color: isMissing ? AppTheme.highlightSurface : AppTheme.surface,
        border: Border.all(
          color: isMissing ? AppTheme.primaryText : AppTheme.borderMuted,
          width: isMissing ? 1.0 : 0.8,
        ),
        borderRadius: BorderRadius.circular(AppTheme.smallRadius),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Icon(
            isMissing ? Icons.priority_high : Icons.check,
            size: 10,
            color: isMissing ? AppTheme.primaryText : AppTheme.secondaryText,
          ),
          const SizedBox(width: 3),
          Text(
            isMissing ? 'MISSING' : 'FOUND',
            style: TextStyle(
              fontSize: 9.5,
              fontWeight: isMissing ? FontWeight.w700 : FontWeight.w600,
              color: isMissing ? AppTheme.primaryText : AppTheme.secondaryText,
              letterSpacing: 0.8,
            ),
          ),
        ],
      ),
    );
  }
}

class RewardLabel extends StatelessWidget {
  final String amount;

  const RewardLabel({super.key, required this.amount});

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 7, vertical: 2.5),
      decoration: BoxDecoration(
        color: AppTheme.surface,
        border: Border.all(color: AppTheme.borderSubtle, width: 0.8),
        borderRadius: BorderRadius.circular(AppTheme.smallRadius),
      ),
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          const Text(
            '§',
            style: TextStyle(
              fontSize: 10,
              fontWeight: FontWeight.bold,
              color: AppTheme.primaryText,
            ),
          ),
          const SizedBox(width: 3),
          Text(
            '$amount Reward',
            style: const TextStyle(
              fontSize: 9.5,
              fontWeight: FontWeight.w600,
              color: AppTheme.primaryText,
              letterSpacing: 0.4,
            ),
          ),
        ],
      ),
    );
  }
}
