import 'dart:math' as math;

import 'package:flutter/material.dart';

import 'theme.dart';

/// The first thing you see: the Cognify logo hovers and glows for three seconds, then the app opens.
class SplashScreen extends StatefulWidget {
  final Widget Function() next;
  const SplashScreen({super.key, required this.next});

  @override
  State<SplashScreen> createState() => _SplashScreenState();
}

class _SplashScreenState extends State<SplashScreen> with SingleTickerProviderStateMixin {
  static const _total = Duration(seconds: 3);
  late final AnimationController _c = AnimationController(vsync: this, duration: _total)..forward();

  @override
  void initState() {
    super.initState();
    _c.addStatusListener((s) {
      if (s == AnimationStatus.completed && mounted) {
        Navigator.of(context).pushReplacement(PageRouteBuilder(
          transitionDuration: const Duration(milliseconds: 450),
          pageBuilder: (_, __, ___) => widget.next(),
          transitionsBuilder: (_, a, __, child) => FadeTransition(opacity: a, child: child),
        ));
      }
    });
  }

  @override
  void dispose() {
    _c.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        backgroundColor: C.bg,
        body: AnimatedBuilder(
          animation: _c,
          builder: (_, __) {
            final t = _c.value * 3;                                     // seconds elapsed
            final hover = math.sin(t * math.pi * 1.1) * 12;               // gentle up and down, about one and a half floats in three seconds
            final breathe = 1 + math.sin(t * math.pi * 1.1) * 0.035;
            final glow = 0.25 + 0.2 * (math.sin(t * math.pi * 1.1) + 1) / 2;
            final word = Curves.easeOut.transform(((t - 0.7) / 0.8).clamp(0.0, 1.0));
            final tag = Curves.easeOut.transform(((t - 1.3) / 0.8).clamp(0.0, 1.0));
            return Stack(alignment: Alignment.center, children: [
              Transform.translate(
                offset: Offset(0, hover),
                child: Transform.scale(
                  scale: breathe,
                  child: Container(
                    width: 112,
                    height: 112,
                    decoration: BoxDecoration(
                      borderRadius: BorderRadius.circular(32),
                      boxShadow: [
                        BoxShadow(color: C.violet.withValues(alpha: glow), blurRadius: 46, spreadRadius: 4),
                        BoxShadow(color: C.cyan.withValues(alpha: glow * 0.6), blurRadius: 70, offset: const Offset(20, 24)),
                      ],
                    ),
                    child: Image.asset('assets/logo_full.png', width: 112, height: 112),
                  ),
                ),
              ),
              Align(
                alignment: const Alignment(0, 0.42),
                child: Opacity(
                  opacity: word,
                  child: Transform.translate(
                    offset: Offset(0, (1 - word) * 10),
                    child: const Text('Cognify', style: TextStyle(fontSize: 34, fontWeight: FontWeight.w800, letterSpacing: -1, color: C.text)),
                  ),
                ),
              ),
              Align(
                alignment: const Alignment(0, 0.54),
                child: Opacity(
                  opacity: tag,
                  child: const Text('Every visit makes the next one smarter', style: TextStyle(fontSize: 14, color: C.mute, letterSpacing: 0.3)),
                ),
              ),
            ]);
          },
        ),
      );
}
