import 'package:flutter/material.dart';
import 'package:google_fonts/google_fonts.dart';

class AppTheme {
  // Strict Monochromatic Palette Tokens
  static const Color background = Color(0xFF080808);
  static const Color surface = Color(0xFF0D0D0D);
  static const Color card = Color(0xFF151515);
  static const Color elevatedSurface = Color(0xFF1C1C1C);
  static const Color highlightSurface = Color(0xFF242424);

  static const Color borderSubtle = Color(0xFF303030);
  static const Color borderMuted = Color(0xFF3A3A3A);
  static const Color borderHighlight = Color(0xFF555555);

  static const Color primaryText = Color(0xFFF5F5F5);
  static const Color secondaryText = Color(0xFFA0A0A0);
  static const Color mutedText = Color(0xFF707070);

  static const Color actionPrimary = Color(0xFFFFFFFF);
  static const Color onActionPrimary = Color(0xFF080808);
  static const Color actionSecondary = Color(0xFF1C1C1C);
  static const Color onActionSecondary = Color(0xFFF5F5F5);

  static const Color divider = Color(0xFF242424);

  // Monochromatic Semantic Equivalents (zero colors)
  static const Color missingColor = Color(
    0xFFF5F5F5,
  ); // High contrast text/border
  static const Color missingBadgeBg = Color(0xFF1C1C1C);
  static const Color foundColor = Color(0xFFA0A0A0); // Muted secondary tone
  static const Color foundBadgeBg = Color(0xFF151515);
  static const Color rewardColor = Color(
    0xFFFFFFFF,
  ); // High-contrast white typography
  static const Color currentLocation = Color(
    0xFFFFFFFF,
  ); // Clean white spatial beacon

  // Architectural Dimensions (Swiss-modernist geometry)
  static const double defaultRadius = 8.0;
  static const double smallRadius = 4.0;
  static const double largeRadius = 12.0;

  static const double spacingXs = 4.0;
  static const double spacingSm = 8.0;
  static const double spacingMd = 16.0;
  static const double spacingLg = 24.0;
  static const double spacingXl = 32.0;

  static ThemeData get darkTheme {
    return ThemeData(
      brightness: Brightness.dark,
      scaffoldBackgroundColor: background,
      primaryColor: actionPrimary,
      dividerColor: divider,
      colorScheme: const ColorScheme.dark(
        primary: actionPrimary,
        onPrimary: onActionPrimary,
        secondary: secondaryText,
        onSecondary: primaryText,
        surface: surface,
        onSurface: primaryText,
      ),
      cardTheme: CardThemeData(
        color: card,
        elevation: 0,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(defaultRadius),
          side: const BorderSide(color: borderSubtle, width: 1.0),
        ),
      ),
      appBarTheme: const AppBarTheme(
        backgroundColor: background,
        elevation: 0,
        centerTitle: false,
        iconTheme: IconThemeData(color: primaryText),
        titleTextStyle: TextStyle(
          color: primaryText,
          fontSize: 16,
          fontWeight: FontWeight.w600,
          letterSpacing: -0.02,
        ),
      ),
      textTheme: GoogleFonts.interTextTheme()
          .copyWith(
            displayLarge: GoogleFonts.hankenGrotesk(
              fontWeight: FontWeight.w700,
              letterSpacing: -0.03,
            ),
            displayMedium: GoogleFonts.hankenGrotesk(
              fontWeight: FontWeight.w700,
              letterSpacing: -0.025,
            ),
            displaySmall: GoogleFonts.hankenGrotesk(
              fontWeight: FontWeight.w600,
              letterSpacing: -0.02,
            ),
            headlineLarge: GoogleFonts.hankenGrotesk(
              fontWeight: FontWeight.w700,
              letterSpacing: -0.025,
            ),
            headlineMedium: GoogleFonts.hankenGrotesk(
              fontWeight: FontWeight.w600,
              letterSpacing: -0.02,
            ),
            headlineSmall: GoogleFonts.hankenGrotesk(
              fontWeight: FontWeight.w600,
              letterSpacing: -0.015,
            ),
            titleLarge: GoogleFonts.hankenGrotesk(
              fontWeight: FontWeight.w600,
              letterSpacing: -0.01,
            ),
            titleMedium: GoogleFonts.hankenGrotesk(
              fontWeight: FontWeight.w500,
              letterSpacing: -0.01,
            ),
            titleSmall: GoogleFonts.inter(
              fontWeight: FontWeight.w500,
              letterSpacing: 0.0,
            ),
            bodyLarge: GoogleFonts.inter(
              fontSize: 15,
              fontWeight: FontWeight.w400,
              letterSpacing: 0.0,
            ),
            bodyMedium: GoogleFonts.inter(
              fontSize: 13,
              fontWeight: FontWeight.w400,
              letterSpacing: 0.0,
            ),
            bodySmall: GoogleFonts.inter(
              fontSize: 11,
              fontWeight: FontWeight.w400,
              letterSpacing: 0.02,
            ),
            labelLarge: GoogleFonts.inter(
              fontSize: 13,
              fontWeight: FontWeight.w500,
              letterSpacing: 0.02,
            ),
            labelMedium: GoogleFonts.inter(
              fontSize: 11,
              fontWeight: FontWeight.w500,
              letterSpacing: 0.04,
            ),
            labelSmall: GoogleFonts.inter(
              fontSize: 10,
              fontWeight: FontWeight.w600,
              letterSpacing: 0.06,
            ),
          )
          .apply(bodyColor: primaryText, displayColor: primaryText),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: actionPrimary,
          foregroundColor: onActionPrimary,
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(defaultRadius),
          ),
          padding: const EdgeInsets.symmetric(
            horizontal: spacingLg,
            vertical: 14,
          ),
          textStyle: const TextStyle(
            fontWeight: FontWeight.w600,
            fontSize: 13,
            letterSpacing: 0.02,
          ),
        ),
      ),
      filledButtonTheme: FilledButtonThemeData(
        style: FilledButton.styleFrom(
          backgroundColor: actionPrimary,
          foregroundColor: onActionPrimary,
          elevation: 0,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(defaultRadius),
          ),
          padding: const EdgeInsets.symmetric(
            horizontal: spacingLg,
            vertical: 14,
          ),
          textStyle: const TextStyle(
            fontWeight: FontWeight.w600,
            fontSize: 13,
            letterSpacing: 0.02,
          ),
        ),
      ),
      outlinedButtonTheme: OutlinedButtonThemeData(
        style: OutlinedButton.styleFrom(
          foregroundColor: primaryText,
          side: const BorderSide(color: borderSubtle, width: 1.0),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(defaultRadius),
          ),
          padding: const EdgeInsets.symmetric(
            horizontal: spacingLg,
            vertical: 14,
          ),
          textStyle: const TextStyle(fontWeight: FontWeight.w500, fontSize: 13),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        fillColor: surface,
        filled: true,
        contentPadding: const EdgeInsets.symmetric(
          horizontal: spacingMd,
          vertical: 14,
        ),
        border: OutlineInputBorder(
          borderRadius: BorderRadius.circular(defaultRadius),
          borderSide: const BorderSide(color: borderSubtle, width: 1.0),
        ),
        enabledBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(defaultRadius),
          borderSide: const BorderSide(color: borderSubtle, width: 1.0),
        ),
        focusedBorder: OutlineInputBorder(
          borderRadius: BorderRadius.circular(defaultRadius),
          borderSide: const BorderSide(color: borderHighlight, width: 1.0),
        ),
        hintStyle: const TextStyle(color: mutedText, fontSize: 13),
      ),
      snackBarTheme: SnackBarThemeData(
        behavior: SnackBarBehavior.floating,
        backgroundColor: card,
        contentTextStyle: const TextStyle(
          color: primaryText,
          fontSize: 13,
          fontWeight: FontWeight.w400,
        ),
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(defaultRadius),
          side: const BorderSide(color: borderSubtle, width: 1.0),
        ),
        elevation: 4.0,
      ),
    );
  }
}
