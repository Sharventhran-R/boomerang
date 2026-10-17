import 'package:flutter/material.dart';
import '../../theme.dart';
import 'login_screen.dart';

class SessionExpiredScreen extends StatelessWidget {
  final VoidCallback? onLoginAgain;
  final VoidCallback? onBackToHome;

  const SessionExpiredScreen({super.key, this.onLoginAgain, this.onBackToHome});

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppTheme.background,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 400),
              child: Column(
                mainAxisAlignment: MainAxisAlignment.center,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  // Lock / Shield Icon
                  Center(
                    child: Container(
                      width: 64,
                      height: 64,
                      decoration: BoxDecoration(
                        color: AppTheme.elevatedSurface,
                        borderRadius: BorderRadius.circular(
                          AppTheme.defaultRadius,
                        ),
                        border: Border.all(color: AppTheme.borderSubtle),
                      ),
                      child: const Icon(
                        Icons.lock_clock_outlined,
                        size: 32,
                        color: AppTheme.primaryText,
                      ),
                    ),
                  ),
                  const SizedBox(height: 24),

                  // Headline
                  const Text(
                    'Please log in again',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontFamily: 'Hanken Grotesk',
                      fontSize: 26,
                      fontWeight: FontWeight.bold,
                      letterSpacing: -0.5,
                      color: AppTheme.primaryText,
                    ),
                  ),
                  const SizedBox(height: 10),
                  const Text(
                    'Your session has expired for your security. Your saved reports and telemetry drafts are safely preserved.',
                    textAlign: TextAlign.center,
                    style: TextStyle(
                      fontSize: 14,
                      color: AppTheme.secondaryText,
                      height: 1.5,
                    ),
                  ),
                  const SizedBox(height: 28),

                  // Data Preservation Proof Module
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
                          width: 36,
                          height: 36,
                          decoration: BoxDecoration(
                            color: AppTheme.elevatedSurface,
                            borderRadius: BorderRadius.circular(
                              AppTheme.smallRadius,
                            ),
                            border: Border.all(color: AppTheme.borderSubtle),
                          ),
                          child: const Icon(
                            Icons.cloud_done_outlined,
                            size: 20,
                            color: AppTheme.primaryText,
                          ),
                        ),
                        const SizedBox(width: 12),
                        const Expanded(
                          child: Column(
                            crossAxisAlignment: CrossAxisAlignment.start,
                            children: [
                              Text(
                                'CACHE INTEGRITY',
                                style: TextStyle(
                                  fontSize: 10,
                                  fontWeight: FontWeight.bold,
                                  letterSpacing: 1.0,
                                  color: AppTheme.secondaryText,
                                ),
                              ),
                              SizedBox(height: 2),
                              Text(
                                'All drafts cached locally',
                                style: TextStyle(
                                  fontSize: 13,
                                  fontWeight: FontWeight.w600,
                                  color: AppTheme.primaryText,
                                ),
                              ),
                            ],
                          ),
                        ),
                        Container(
                          padding: const EdgeInsets.symmetric(
                            horizontal: 8,
                            vertical: 3,
                          ),
                          decoration: BoxDecoration(
                            color: AppTheme.elevatedSurface,
                            borderRadius: BorderRadius.circular(
                              AppTheme.smallRadius,
                            ),
                            border: Border.all(color: AppTheme.borderMuted),
                          ),
                          child: const Text(
                            'SYNCED',
                            style: TextStyle(
                              fontSize: 10,
                              fontWeight: FontWeight.bold,
                              letterSpacing: 0.8,
                              color: AppTheme.primaryText,
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 28),

                  // Primary Action: Log In
                  ElevatedButton.icon(
                    onPressed: () {
                      if (onLoginAgain != null) {
                        onLoginAgain!();
                      } else {
                        Navigator.pushReplacement(
                          context,
                          MaterialPageRoute(
                            builder: (_) => const LoginScreen(),
                          ),
                        );
                      }
                    },
                    icon: const Icon(Icons.arrow_forward, size: 18),
                    label: const Text(
                      'Log In',
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.bold,
                      ),
                    ),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppTheme.actionPrimary,
                      foregroundColor: AppTheme.onActionPrimary,
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(
                          AppTheme.smallRadius,
                        ),
                      ),
                      elevation: 0,
                    ),
                  ),
                  const SizedBox(height: 12),

                  // Secondary Action: Back to Home
                  OutlinedButton(
                    onPressed: () {
                      if (onBackToHome != null) {
                        onBackToHome!();
                      } else if (Navigator.of(context).canPop()) {
                        Navigator.of(context).pop();
                      }
                    },
                    style: OutlinedButton.styleFrom(
                      foregroundColor: AppTheme.primaryText,
                      padding: const EdgeInsets.symmetric(vertical: 14),
                      side: const BorderSide(color: AppTheme.borderMuted),
                      shape: RoundedRectangleBorder(
                        borderRadius: BorderRadius.circular(
                          AppTheme.smallRadius,
                        ),
                      ),
                    ),
                    child: const Text(
                      'Back to Home',
                      style: TextStyle(
                        fontSize: 14,
                        fontWeight: FontWeight.w600,
                      ),
                    ),
                  ),
                  const SizedBox(height: 28),

                  // Session ID Telemetry
                  const Center(
                    child: Text(
                      'ENC-SESSION // ID: 8F4-09A9-NX',
                      style: TextStyle(
                        fontSize: 10,
                        letterSpacing: 1.0,
                        fontWeight: FontWeight.bold,
                        color: AppTheme.mutedText,
                      ),
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
}
