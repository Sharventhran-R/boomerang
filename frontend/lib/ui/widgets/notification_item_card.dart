import 'package:flutter/material.dart';
import '../../models/notification_model.dart';
import '../../services/notification_repository.dart';
import '../../theme.dart';

/// Card widget rendering a single notification item in the notification centre.
class NotificationItemCard extends StatelessWidget {
  final NotificationItemModel item;
  final VoidCallback? onMarkRead;

  const NotificationItemCard({super.key, required this.item, this.onMarkRead});

  String _formatTimestamp(DateTime dt) {
    final now = DateTime.now();
    final diff = now.difference(dt);

    if (diff.inSeconds < 60) {
      return 'Just now';
    } else if (diff.inMinutes < 60) {
      return '${diff.inMinutes}m ago';
    } else if (diff.inHours < 24) {
      return '${diff.inHours}h ago';
    } else if (diff.inDays < 7) {
      return '${diff.inDays}d ago';
    } else {
      return '${dt.year}-${dt.month.toString().padLeft(2, '0')}-${dt.day.toString().padLeft(2, '0')}';
    }
  }

  IconData _getTypeIcon(String type) {
    final cleanType = type.toLowerCase();
    if (cleanType.contains('match')) {
      return Icons.auto_awesome;
    } else if (cleanType.contains('recovery')) {
      return Icons.swap_horiz;
    } else if (cleanType.contains('report')) {
      return Icons.inventory_2_outlined;
    }
    return Icons.notifications_outlined;
  }

  String _getTypeLabel(String type) {
    final cleanType = type.toLowerCase();
    if (cleanType.contains('match')) {
      return 'MATCH ALERT';
    } else if (cleanType.contains('recovery')) {
      return 'RECOVERY UPDATE';
    } else if (cleanType.contains('report')) {
      return 'REPORT STATUS';
    }
    return 'NOTIFICATION';
  }

  @override
  Widget build(BuildContext context) {
    final isUnread = !item.isRead;
    final isHighPriority =
        item.priority.toLowerCase() == 'high' ||
        item.priority.toLowerCase() == 'urgent';

    return Semantics(
      label:
          '${isUnread ? "Unread" : "Read"} notification. ${_getTypeLabel(item.type)}. ${item.title}. ${item.body}. Received ${_formatTimestamp(item.createdAt)}.',
      button: isUnread,
      child: Material(
        color: Colors.transparent,
        child: InkWell(
          onTap: () {
            if (isUnread) {
              if (onMarkRead != null) {
                onMarkRead!();
              } else {
                NotificationRepository.instance.markAsRead(item.id);
              }
            }
          },
          borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
          child: Container(
            decoration: BoxDecoration(
              color: isUnread ? AppTheme.card : AppTheme.surface,
              borderRadius: BorderRadius.circular(AppTheme.defaultRadius),
              border: Border.all(
                color: isUnread ? AppTheme.borderMuted : AppTheme.borderSubtle,
                width: isUnread ? 1.2 : 0.8,
              ),
            ),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                // Visual accent indicator bar for unread or high-priority
                Container(
                  width: 4,
                  height: 96,
                  decoration: BoxDecoration(
                    color: isHighPriority
                        ? AppTheme.actionPrimary
                        : (isUnread
                              ? AppTheme.secondaryText
                              : Colors.transparent),
                    borderRadius: const BorderRadius.only(
                      topLeft: Radius.circular(AppTheme.defaultRadius),
                      bottomLeft: Radius.circular(AppTheme.defaultRadius),
                    ),
                  ),
                ),
                Expanded(
                  child: Padding(
                    padding: const EdgeInsets.all(14.0),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        // Header row: Type badge, Priority badge, and timestamp
                        Row(
                          children: [
                            Icon(
                              _getTypeIcon(item.type),
                              size: 14,
                              color: isUnread
                                  ? AppTheme.primaryText
                                  : AppTheme.secondaryText,
                            ),
                            const SizedBox(width: 6),
                            Text(
                              _getTypeLabel(item.type),
                              style: TextStyle(
                                fontSize: 10,
                                fontWeight: FontWeight.bold,
                                letterSpacing: 0.8,
                                color: isUnread
                                    ? AppTheme.primaryText
                                    : AppTheme.mutedText,
                              ),
                            ),
                            if (isHighPriority) ...[
                              const SizedBox(width: 8),
                              Container(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 5,
                                  vertical: 1.5,
                                ),
                                decoration: BoxDecoration(
                                  color: AppTheme.actionPrimary,
                                  borderRadius: BorderRadius.circular(
                                    AppTheme.smallRadius,
                                  ),
                                ),
                                child: const Text(
                                  'HIGH PRIORITY',
                                  style: TextStyle(
                                    fontSize: 8.5,
                                    fontWeight: FontWeight.w800,
                                    letterSpacing: 0.5,
                                    color: AppTheme.onActionPrimary,
                                  ),
                                ),
                              ),
                            ],
                            const Spacer(),
                            Text(
                              _formatTimestamp(item.createdAt),
                              style: const TextStyle(
                                fontSize: 11,
                                color: AppTheme.secondaryText,
                              ),
                            ),
                            if (isUnread) ...[
                              const SizedBox(width: 8),
                              Container(
                                width: 7,
                                height: 7,
                                decoration: const BoxDecoration(
                                  color: AppTheme.actionPrimary,
                                  shape: BoxShape.circle,
                                ),
                              ),
                            ],
                          ],
                        ),
                        const SizedBox(height: 8),

                        // Title
                        Text(
                          item.title,
                          style: TextStyle(
                            fontSize: 14,
                            fontWeight: isUnread
                                ? FontWeight.w700
                                : FontWeight.w500,
                            color: isUnread
                                ? AppTheme.primaryText
                                : AppTheme.secondaryText,
                          ),
                          maxLines: 2,
                          overflow: TextOverflow.ellipsis,
                        ),
                        const SizedBox(height: 4),

                        // Body
                        Text(
                          item.body,
                          style: const TextStyle(
                            fontSize: 12.5,
                            height: 1.35,
                            color: AppTheme.secondaryText,
                          ),
                          maxLines: 3,
                          overflow: TextOverflow.ellipsis,
                        ),

                        if (isUnread) ...[
                          const SizedBox(height: 10),
                          Align(
                            alignment: Alignment.centerRight,
                            child: InkWell(
                              onTap: () {
                                if (onMarkRead != null) {
                                  onMarkRead!();
                                } else {
                                  NotificationRepository.instance.markAsRead(
                                    item.id,
                                  );
                                }
                              },
                              borderRadius: BorderRadius.circular(
                                AppTheme.smallRadius,
                              ),
                              child: Padding(
                                padding: const EdgeInsets.symmetric(
                                  horizontal: 6,
                                  vertical: 3,
                                ),
                                child: Row(
                                  mainAxisSize: MainAxisSize.min,
                                  children: const [
                                    Icon(
                                      Icons.check,
                                      size: 13,
                                      color: AppTheme.mutedText,
                                    ),
                                    SizedBox(width: 4),
                                    Text(
                                      'Mark as read',
                                      style: TextStyle(
                                        fontSize: 11,
                                        fontWeight: FontWeight.w600,
                                        color: AppTheme.secondaryText,
                                      ),
                                    ),
                                  ],
                                ),
                              ),
                            ),
                          ),
                        ],
                      ],
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
