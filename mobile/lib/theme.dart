import 'dart:convert';

import 'package:flutter/material.dart';

/// The same dark palette as the website.
class C {
  static const bg = Color(0xFF0B1020);
  static const s1 = Color(0xFF10162A);
  static const s2 = Color(0xFF151C33);
  static const s3 = Color(0xFF1F2745);
  static const line = Color(0xFF232C52);
  static const line2 = Color(0xFF2C3560);
  static const text = Color(0xFFE8ECF8);
  static const mute = Color(0xFF8F9BC0);
  static const dim = Color(0xFF6C769C);
  static const violet = Color(0xFF8B5CF6);
  static const violet2 = Color(0xFFA78BFA);
  static const deep = Color(0xFF241D52);
  static const cyan = Color(0xFF22D3EE);
  static const ok = Color(0xFF34D399);
  static const amber = Color(0xFFFBBF24);
  static const red = Color(0xFFFB7185);
}

ThemeData buildTheme() {
  final base = ThemeData.dark(useMaterial3: true);
  return base.copyWith(
    scaffoldBackgroundColor: C.bg,
    colorScheme: const ColorScheme.dark(
      primary: C.violet,
      secondary: C.cyan,
      surface: C.s1,
      error: C.red,
    ),
    appBarTheme: const AppBarTheme(backgroundColor: C.bg, foregroundColor: C.text, elevation: 0, scrolledUnderElevation: 0),
    navigationBarTheme: NavigationBarThemeData(
      backgroundColor: C.s1,
      indicatorColor: C.deep,
      labelTextStyle: WidgetStateProperty.all(const TextStyle(fontSize: 12, fontWeight: FontWeight.w600)),
    ),
    inputDecorationTheme: InputDecorationTheme(
      filled: true,
      fillColor: C.s2,
      border: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: const BorderSide(color: C.line2)),
      enabledBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: const BorderSide(color: C.line2)),
      focusedBorder: OutlineInputBorder(borderRadius: BorderRadius.circular(14), borderSide: const BorderSide(color: C.violet)),
      labelStyle: const TextStyle(color: C.mute),
      hintStyle: const TextStyle(color: C.dim),
    ),
    filledButtonTheme: FilledButtonThemeData(
      style: FilledButton.styleFrom(
        backgroundColor: C.violet,
        foregroundColor: Colors.white,
        padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 14),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(99)),
        textStyle: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15),
      ),
    ),
    outlinedButtonTheme: OutlinedButtonThemeData(
      style: OutlinedButton.styleFrom(
        foregroundColor: C.text,
        side: const BorderSide(color: C.line2),
        padding: const EdgeInsets.symmetric(horizontal: 18, vertical: 12),
        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(99)),
      ),
    ),
    dividerColor: C.line,
  );
}

/// A rounded dark card used everywhere.
class Panel extends StatelessWidget {
  final Widget child;
  final EdgeInsets padding;
  final Color? color;
  final Color? border;
  final VoidCallback? onTap;
  const Panel({super.key, required this.child, this.padding = const EdgeInsets.all(16), this.color, this.border, this.onTap});

  @override
  Widget build(BuildContext context) {
    final box = Container(
      width: double.infinity,
      padding: padding,
      decoration: BoxDecoration(
        color: color ?? C.s1,
        borderRadius: BorderRadius.circular(18),
        border: Border.all(color: border ?? C.line),
      ),
      child: child,
    );
    if (onTap == null) return box;
    return Material(
      color: Colors.transparent,
      child: InkWell(borderRadius: BorderRadius.circular(18), onTap: onTap, child: box),
    );
  }
}

class Pill extends StatelessWidget {
  final String text;
  final Color color;
  const Pill(this.text, {super.key, this.color = C.mute});

  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
        decoration: BoxDecoration(
          color: color.withValues(alpha: 0.14),
          borderRadius: BorderRadius.circular(99),
          border: Border.all(color: color.withValues(alpha: 0.5)),
        ),
        child: Text(text, style: TextStyle(color: color, fontSize: 12, fontWeight: FontWeight.w700)),
      );
}

Color confidenceColor(String c) {
  final s = c.toLowerCase();
  if (s.contains('high')) return C.ok;
  if (s.contains('medium')) return C.cyan;
  if (s.contains('weak') || s.contains('no history') || s.contains('none')) return C.amber;
  return C.red;
}

Color agentColor(String a) {
  switch (a) {
    case 'dispatcher':
      return C.cyan;
    case 'diagnostician':
      return C.violet2;
    case 'parts':
      return C.amber;
    case 'verifier':
      return C.ok;
    default:
      return C.mute;
  }
}

/// The optional picture of the unit that the reporter attached, sent as a data: URL.
Widget unitPhoto(Object? dataUrl) {
  final u = dataUrl is String ? dataUrl : '';
  final i = u.indexOf(',');
  if (!u.startsWith('data:image/') || i < 0) return const SizedBox.shrink();
  try {
    return Padding(
      padding: const EdgeInsets.only(top: 14),
      child: ClipRRect(borderRadius: BorderRadius.circular(14), child: Image.memory(base64Decode(u.substring(i + 1)), height: 170, width: double.infinity, fit: BoxFit.cover)),
    );
  } catch (_) {
    return const SizedBox.shrink();
  }
}
