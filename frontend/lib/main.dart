import 'package:flutter/material.dart';
import 'services/auth_service.dart';
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
  runApp(const BoomerangApp());
}

class BoomerangApp extends StatelessWidget {
  final Widget? home;

  const BoomerangApp({super.key, this.home});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Boomerang',
      theme: AppTheme.darkTheme,
      home: home ?? const AppRoot(),
      debugShowCheckedModeBanner: false,
    );
  }
}

class AppRoot extends StatelessWidget {
  const AppRoot({super.key});

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
        return const MainNavScreen();
      },
    );
  }
}
