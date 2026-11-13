import 'package:flutter/material.dart';

import 'api.dart';
import 'push.dart';
import 'roles.dart';
import 'splash.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await Api.load();
  runApp(const CognifyField());
  Push.init(); // after the first screen is up, and never blocks it
}

class CognifyField extends StatelessWidget {
  const CognifyField({super.key});

  @override
  Widget build(BuildContext context) => MaterialApp(
        title: 'Cognify Field',
        debugShowCheckedModeBanner: false,
        theme: buildTheme(),
        home: SplashScreen(next: () => Api.token == null ? const ConnectScreen() : homeFor()),
      );
}

class ConnectScreen extends StatefulWidget {
  const ConnectScreen({super.key});

  @override
  State<ConnectScreen> createState() => _ConnectScreenState();
}

class _ConnectScreenState extends State<ConnectScreen> {
  final _url = TextEditingController(text: Api.base);
  bool _busy = false;
  String? _error;

  Future<void> _connect() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      Api.base = _url.text.trim().replaceAll(RegExp(r'/+$'), '');
      if (!Api.base.startsWith('http')) Api.base = 'http://${Api.base}';
      await Api.get('/api/status');
      final r = await Api.post('/api/workspace/guest', {});
      Api.token = r['token'] as String;
      await Api.save();
      if (!mounted) return;
      Navigator.of(context).pushReplacement(MaterialPageRoute(builder: (_) => homeFor()));
    } on ApiError catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        body: SafeArea(
          child: ListView(
            padding: const EdgeInsets.fromLTRB(24, 48, 24, 24),
            children: [
              Align(
                alignment: Alignment.centerLeft,
                child: Container(
                  width: 64,
                  height: 64,
                  decoration: BoxDecoration(
                    gradient: const LinearGradient(colors: [C.violet, C.cyan]),
                    borderRadius: BorderRadius.circular(20),
                  ),
                  child: const Icon(Icons.hearing_rounded, size: 34, color: Colors.white),
                ),
              ),
              const SizedBox(height: 28),
              const Text('Cognify Field', style: TextStyle(fontSize: 38, fontWeight: FontWeight.w800, letterSpacing: -1.2, height: 1.05)),
              const SizedBox(height: 10),
              const Text(
                'The technician app. See the job, get the briefing from four agents that remember every past repair, and log what happened so the next person knows.',
                style: TextStyle(color: C.mute, fontSize: 15.5, height: 1.5),
              ),
              const SizedBox(height: 32),
              TextField(
                controller: _url,
                keyboardType: TextInputType.url,
                decoration: const InputDecoration(labelText: 'Server', hintText: 'http://192.168.x.x:8000', prefixIcon: Icon(Icons.wifi_rounded, color: C.mute)),
              ),
              const SizedBox(height: 6),
              const Text('Use the address of the laptop running Cognify, on the same Wi-Fi.', style: TextStyle(color: C.dim, fontSize: 12.5)),
              if (_error != null) ...[
                const SizedBox(height: 14),
                Panel(color: const Color(0xFF2E1018), border: const Color(0xFF7A2638), child: Text(_error!, style: const TextStyle(color: C.red))),
              ],
              const SizedBox(height: 22),
              FilledButton(
                onPressed: _busy ? null : _connect,
                child: _busy
                    ? const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2.4, color: Colors.white))
                    : const Text('Join the demo company'),
              ),
              const SizedBox(height: 14),
              const Text('Demo data: a fictional Bengaluru HVAC contractor. No real customers.', style: TextStyle(color: C.dim, fontSize: 12.5)),
            ],
          ),
        ),
      );
}
