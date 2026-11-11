import 'package:flutter/material.dart';
import 'services/auth_service.dart';
import 'services/fcm_service.dart';
import 'services/match_repository.dart';
import 'services/notification_repository.dart';
import 'services/notification_router.dart';
import 'services/recovery_repository.dart';
import 'services/report_repository.dart';
import 'theme.dart';
import 'ui/screens/login_screen.dart';
import 'ui/screens/main_nav_screen.dart';

void main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await AuthService.instance.restoreSession();
  ReportRepository.instance.configure();
  RecoveryRepository.instance.configure();
  MatchRepository.instance.configure();
  NotificationRepository.instance.configure();
  await FCMService.instance.initialize();
  await FCMService.instance.checkInitialMessage();
  runApp(const BoomerangApp());
}

class BoomerangApp extends StatelessWidget {
  final Widget? home;
  final GlobalKey<NavigatorState>? navigatorKey;

  const BoomerangApp({super.key, this.home, this.navigatorKey});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      navigatorKey: navigatorKey ?? NotificationRouter.navigatorKey,
      title: 'Boomerang',
      theme: AppTheme.darkTheme,
      home: home ?? const AppRoot(),
      debugShowCheckedModeBanner: false,
    );
  }
}

class AppRoot extends StatefulWidget {
  const AppRoot({super.key});

  @override
  State<AppRoot> createState() => _AppRootState();
}

class _AppRootState extends State<AppRoot> {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) {
      if (AuthService.instance.isAuthenticated) {
        NotificationRouter.instance.processPendingRoute();
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return ListenableBuilder(
      listenable: AuthService.instance,
      builder: (context, _) {
        if (!AuthService.instance.isAuthenticated) {
          // If in standalone test mock mode where AuthService was not initialized,
          // maintain backwards compatibility for existing widget tests
          if (ReportRepository.instance.isMockMode &&
              !AuthService.instance.isInitialized) {
            return const MainNavScreen();
          }
          return const LoginScreen();
        }
        WidgetsBinding.instance.addPostFrameCallback((_) {
          NotificationRouter.instance.processPendingRoute();
        });
        return const MainNavScreen();
      },
    );
  }
}
