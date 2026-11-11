import 'package:flutter/material.dart';
import '../../services/notification_repository.dart';
import '../../theme.dart';
import '../screens/notifications_screen.dart';

/// Monochromatic notification badge icon with live unread counter.
class NotificationBadgeIcon extends StatelessWidget {
  final VoidCallback? onTap;
  final Color? iconColor;
  final double iconSize;

  const NotificationBadgeIcon({
    super.key,
    this.onTap,
    this.iconColor,
    this.iconSize = 22.0,
  });

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: NotificationRepository.instance,
      builder: (context, _) {
        final unreadCount = NotificationRepository.instance.unreadCount;
        final countText = unreadCount > 99 ? '99+' : unreadCount.toString();
        final hasUnread = unreadCount > 0;

        return Semantics(
          button: true,
          label: hasUnread
              ? 'Notifications, $unreadCount unread notifications'
              : 'Notifications, no unread notifications',
          child: Tooltip(
            message: hasUnread
                ? 'Notifications ($unreadCount unread)'
                : 'Notifications',
            child: InkWell(
              onTap:
                  onTap ??
                  () {
                    Navigator.push(
                      context,
                      MaterialPageRoute(
                        builder: (_) => const NotificationsScreen(),
                      ),
                    );
                  },
              borderRadius: BorderRadius.circular(AppTheme.smallRadius),
              child: Padding(
                padding: const EdgeInsets.all(8.0),
                child: Stack(
                  clipBehavior: Clip.none,
                  children: [
                    Icon(
                      hasUnread
                          ? Icons.notifications_active_outlined
                          : Icons.notifications_outlined,
                      size: iconSize,
                      color: iconColor ?? AppTheme.primaryText,
                    ),
                    if (hasUnread)
                      Positioned(
                        right: -4,
                        top: -4,
                        child: Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 4,
                            vertical: 1.5,
                          ),
                          constraints: const BoxConstraints(
                            minWidth: 16,
                            minHeight: 16,
                          ),
                          decoration: BoxDecoration(
                            color: AppTheme.actionPrimary,
                            borderRadius: BorderRadius.circular(10),
                            border: Border.all(
                              color: AppTheme.background,
                              width: 1.5,
                            ),
                          ),
                          alignment: Alignment.center,
                          child: Text(
                            countText,
                            style: const TextStyle(
                              color: AppTheme.onActionPrimary,
                              fontSize: 9.5,
                              fontWeight: FontWeight.w800,
                              height: 1.0,
                            ),
                            textAlign: TextAlign.center,
                          ),
                        ),
                      ),
                  ],
                ),
              ),
            ),
          ),
        );
      },
    );
  }
}
