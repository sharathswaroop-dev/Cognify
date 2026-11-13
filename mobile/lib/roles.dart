import 'dart:async';
import 'dart:convert';

import 'package:flutter/material.dart';
import 'package:image_picker/image_picker.dart';

import 'api.dart';
import 'jobs.dart';
import 'main.dart';
import 'push.dart';
import 'tech.dart';
import 'theme.dart';

/// Where the signed-in person lands.
Widget homeFor() {
  final u = Api.user;
  if (u == null) return const RoleScreen();
  return s(u['role']) == 'reporter' ? const ReporterShell() : const TechShell();
}

Future<void> signOut(BuildContext context) async {
  await Push.forget();
  Api.user = null;
  Api.token = null;
  Api.session = null;
  await Api.save();
  if (context.mounted) {
    Navigator.of(context).pushAndRemoveUntil(MaterialPageRoute(builder: (_) => const ConnectScreen()), (_) => false);
  }
}

// ============================================================ who are you
class RoleScreen extends StatefulWidget {
  const RoleScreen({super.key});

  @override
  State<RoleScreen> createState() => _RoleScreenState();
}

class _RoleScreenState extends State<RoleScreen> {
  String? _role;
  Map<String, dynamic>? _meta;
  final _name = TextEditingController();
  final _spec = TextEditingController(text: 'General HVAC');
  final _code = TextEditingController();
  String? _site;
  bool _newTech = false;
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _loadMeta();
  }

  Future<void> _loadMeta() async {
    try {
      final r = m(await Api.get('/api/dispatch/meta'));
      if (mounted) {
        setState(() {
          _meta = r;
          final sites = l(r['sites']);
          if (sites.isNotEmpty) _site = s(m(sites.first)['id']);
        });
      }
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  Future<void> _enter(Map<String, dynamic> user) async {
    Api.session = user['session'] is String ? user['session'] as String : null;
    Api.user = {...user}..remove('session');
    await Api.save();
    Push.register(); // this phone now belongs to the person who signed in
    if (!mounted) return;
    Navigator.of(context).pushAndRemoveUntil(MaterialPageRoute(builder: (_) => homeFor()), (_) => false);
  }

  /// An existing technician signs in with the company's code.
  Future<void> _login(String tid) async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final u = m(await Api.post('/api/dispatch/login', {'tech_id': tid, 'company_code': _code.text.trim()}));
      await _enter(u);
    } on ApiError catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  Future<void> _register() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final body = <String, dynamic>{'name': _name.text.trim(), 'role': _role};
      if (_role == 'reporter') body['site_id'] = _site;
      if (_role == 'technician') {
        body['speciality'] = _spec.text.trim();
        body['company_code'] = _code.text.trim();
      }
      final u = m(await Api.post('/api/dispatch/register', body));
      await _enter({...u, 'role': _role});
    } on ApiError catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        appBar: AppBar(
          leading: _role == null ? null : IconButton(onPressed: () => setState(() => _role = null), icon: const Icon(Icons.arrow_back_rounded)),
          title: const Text('Who are you?'),
        ),
        body: ListView(padding: const EdgeInsets.fromLTRB(20, 8, 20, 32), children: [
          if (_role == null) ...[
            const Text('Pick how you will use Cognify. You can sign out and switch any time.', style: TextStyle(color: C.mute, height: 1.45)),
            const SizedBox(height: 18),
            _RoleCard(
              icon: Icons.report_problem_rounded,
              color: C.amber,
              title: 'I report problems',
              text: 'A facility manager or customer. Report a fault, see who is sent, and follow them to your door.',
              onTap: () => setState(() => _role = 'reporter'),
            ),
            const SizedBox(height: 12),
            _RoleCard(
              icon: Icons.engineering_rounded,
              color: C.cyan,
              title: 'I am a technician',
              text: 'Get job offers near you, accept them, get the briefing from four agents that remember every repair, and log the visit.',
              onTap: () => setState(() => _role = 'technician'),
            ),
          ] else if (_role == 'reporter') ...[
            const Text('Report problems', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800, letterSpacing: -0.6)),
            const SizedBox(height: 16),
            TextField(controller: _name, textCapitalization: TextCapitalization.words, decoration: const InputDecoration(labelText: 'Your name', hintText: 'e.g. Priya Nair')),
            const SizedBox(height: 12),
            if (_meta != null)
              DropdownButtonFormField<String>(
                initialValue: _site,
                isExpanded: true,
                dropdownColor: C.s2,
                decoration: const InputDecoration(labelText: 'Your site'),
                items: [for (final x in l(_meta!['sites'])) DropdownMenuItem(value: s(m(x)['id']), child: Text('${s(m(x)['name'])} · ${s(m(x)['area'])}', overflow: TextOverflow.ellipsis))],
                onChanged: (v) => setState(() => _site = v),
              ),
            _err(),
            const SizedBox(height: 18),
            FilledButton(onPressed: _busy ? null : _register, child: _busy ? const _Spin() : const Text('Create my account')),
          ] else ...[
            const Text('Technician', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800, letterSpacing: -0.6)),
            const SizedBox(height: 6),
            const Text('Sign in as one of the demo technicians, or join as a new one.', style: TextStyle(color: C.mute)),
            const SizedBox(height: 14),
            if (!_newTech && _meta != null) ...[
              TextField(
                controller: _code,
                textCapitalization: TextCapitalization.characters,
                decoration: const InputDecoration(labelText: 'Company code', hintText: 'Ask your company (demo: COOLCARE-DEMO)', prefixIcon: Icon(Icons.vpn_key_rounded, color: C.mute)),
              ),
              _err(),
              const SizedBox(height: 14),
              for (final t in l(_meta!['technicians']))
                Padding(
                  padding: const EdgeInsets.only(bottom: 10),
                  child: Panel(
                    onTap: () => _busy ? null : _login(s(m(t)['id'])),
                    child: Row(children: [
                      CircleAvatar(backgroundColor: C.deep, child: Text(s(m(t)['name']).substring(0, 1), style: const TextStyle(fontWeight: FontWeight.w800, color: C.violet2))),
                      const SizedBox(width: 14),
                      Expanded(
                        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                          Text(s(m(t)['name']), style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                          Text('${s(m(t)['speciality'])} · ${s(m(t)['years'])} yr', style: const TextStyle(color: C.mute, fontSize: 13)),
                        ]),
                      ),
                      const Icon(Icons.chevron_right_rounded, color: C.dim),
                    ]),
                  ),
                ),
              OutlinedButton.icon(onPressed: () => setState(() => _newTech = true), icon: const Icon(Icons.person_add_alt_1_rounded), label: const Text('Join as a new technician')),
            ] else ...[
              TextField(controller: _name, textCapitalization: TextCapitalization.words, decoration: const InputDecoration(labelText: 'Your name')),
              const SizedBox(height: 12),
              TextField(controller: _spec, decoration: const InputDecoration(labelText: 'Speciality', hintText: 'e.g. VRV / VRF systems')),
              const SizedBox(height: 12),
              TextField(
                controller: _code,
                textCapitalization: TextCapitalization.characters,
                decoration: const InputDecoration(labelText: 'Company code', hintText: 'Only the company’s own technicians can join', prefixIcon: Icon(Icons.vpn_key_rounded, color: C.mute)),
              ),
              _err(),
              const SizedBox(height: 18),
              FilledButton(onPressed: _busy ? null : _register, child: _busy ? const _Spin() : const Text('Join the team')),
            ],
          ],
          if (_role == null) _err(),
        ]),
      );

  Widget _err() => _error == null
      ? const SizedBox.shrink()
      : Padding(padding: const EdgeInsets.only(top: 14), child: Panel(color: const Color(0xFF2E1018), border: const Color(0xFF7A2638), child: Text(_error!, style: const TextStyle(color: C.red))));
}

class _Spin extends StatelessWidget {
  const _Spin();

  @override
  Widget build(BuildContext context) => const SizedBox(width: 20, height: 20, child: CircularProgressIndicator(strokeWidth: 2.4, color: Colors.white));
}

class _RoleCard extends StatelessWidget {
  final IconData icon;
  final Color color;
  final String title, text;
  final VoidCallback onTap;
  const _RoleCard({required this.icon, required this.color, required this.title, required this.text, required this.onTap});

  @override
  Widget build(BuildContext context) => Panel(
        onTap: onTap,
        padding: const EdgeInsets.all(20),
        child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
          Container(
            width: 52,
            height: 52,
            decoration: BoxDecoration(color: color.withValues(alpha: 0.14), borderRadius: BorderRadius.circular(16), border: Border.all(color: color.withValues(alpha: 0.5))),
            child: Icon(icon, color: color, size: 28),
          ),
          const SizedBox(width: 16),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(title, style: const TextStyle(fontSize: 19, fontWeight: FontWeight.w800)),
              const SizedBox(height: 4),
              Text(text, style: const TextStyle(color: C.mute, height: 1.45)),
            ]),
          ),
        ]),
      );
}

// ============================================================ the reporter's app
class ReporterShell extends StatefulWidget {
  const ReporterShell({super.key});

  @override
  State<ReporterShell> createState() => _ReporterShellState();
}

class _ReporterShellState extends State<ReporterShell> {
  int _tab = 0;

  @override
  Widget build(BuildContext context) {
    final name = s(Api.user?['name']);
    final pages = <Widget>[ReportScreen(onSent: () => setState(() => _tab = 1)), const MyReportsScreen(), const _HelpScreen()];
    return Scaffold(
      appBar: AppBar(
        titleSpacing: 16,
        title: const Text('Cognify', style: TextStyle(fontWeight: FontWeight.w800, letterSpacing: -0.5)),
        actions: [
          Pill(name, color: C.violet2),
          IconButton(onPressed: () => signOut(context), icon: const Icon(Icons.logout_rounded, color: C.mute), tooltip: 'Sign out'),
        ],
      ),
      body: IndexedStack(index: _tab, children: pages),
      bottomNavigationBar: NavigationBar(
        selectedIndex: _tab,
        onDestinationSelected: (i) => setState(() => _tab = i),
        destinations: const [
          NavigationDestination(icon: Icon(Icons.add_circle_outline_rounded), selectedIcon: Icon(Icons.add_circle_rounded), label: 'Report'),
          NavigationDestination(icon: Icon(Icons.list_alt_rounded), selectedIcon: Icon(Icons.list_alt_rounded), label: 'My reports'),
          NavigationDestination(icon: Icon(Icons.help_outline_rounded), selectedIcon: Icon(Icons.help_rounded), label: 'Help'),
        ],
      ),
    );
  }
}

/// What a reporter needs to know. Repair advice stays with the technician's assistant; a reporter only raises the problem and follows it.
class _HelpScreen extends StatelessWidget {
  const _HelpScreen();

  Widget _item(IconData icon, String title, String body) => Padding(
        padding: const EdgeInsets.only(bottom: 12),
        child: Panel(
          child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
            Icon(icon, color: C.violet2),
            const SizedBox(width: 14),
            Expanded(
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Text(title, style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 15.5)),
                const SizedBox(height: 4),
                Text(body, style: const TextStyle(color: C.mute, height: 1.45)),
              ]),
            ),
          ]),
        ),
      );

  @override
  Widget build(BuildContext context) => ListView(padding: const EdgeInsets.fromLTRB(16, 8, 16, 24), children: [
        const Text('How it works', style: TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
        const SizedBox(height: 14),
        _item(Icons.radar_rounded, 'The nearest good match is found for you', 'Technicians close to your site are asked first. If nobody nearby accepts, the search widens layer by layer.'),
        _item(Icons.photo_camera_outlined, 'A photo helps', 'It is optional, but a picture of the unit or its error display lets the technician arrive prepared.'),
        _item(Icons.pin_outlined, 'The OTP', 'When the technician arrives, tell them the 4-digit code shown on your request. Work only starts once they enter it.'),
        _item(Icons.science_outlined, 'Demo and Manual', 'Demo: the other technicians answer by themselves so the whole story plays on its own. Manual: a real technician, or the presenter, decides.'),
      ]);
}

class ReportScreen extends StatefulWidget {
  final VoidCallback onSent;
  const ReportScreen({super.key, required this.onSent});

  @override
  State<ReportScreen> createState() => _ReportScreenState();
}

class _ReportScreenState extends State<ReportScreen> {
  Map<String, dynamic>? _meta;
  String? _site, _machine;
  String _sev = 'high';
  bool _manual = false;
  String? _photo; // optional picture of the unit, as a data: URL

  Future<void> _pickPhoto() async {
    try {
      final f = await ImagePicker().pickImage(source: ImageSource.gallery, maxWidth: 900, imageQuality: 70);
      if (f == null) return;
      final bytes = await f.readAsBytes();
      if (mounted) setState(() => _photo = 'data:image/jpeg;base64,${base64Encode(bytes)}');
    } catch (_) {
      if (mounted) setState(() => _error = 'Could not open the photo. You can still send the report without one.');
    }
  }

  int? _plan; // Demo mode: how many technicians decline before one accepts (null = random, -1 = nobody)
  final _text = TextEditingController();
  bool _busy = false;
  String? _error;

  @override
  void initState() {
    super.initState();
    _load();
  }

  @override
  void dispose() {
    _text.dispose();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final r = m(await Api.get('/api/dispatch/meta'));
      if (!mounted) return;
      setState(() {
        _meta = r;
        final sites = l(r['sites']).map(m).toList();
        final mine = s(Api.user?['site_id']);
        _site = sites.any((x) => s(x['id']) == mine) ? mine : s(sites.first['id']);
        _pickMachine();
      });
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  List<Map<String, dynamic>> get _machines {
    final site = l(_meta?['sites']).map(m).firstWhere((x) => s(x['id']) == _site, orElse: () => <String, dynamic>{});
    return l(site['machines']).map(m).toList();
  }

  String get _typical {
    final hit = _machines.where((x) => s(x['id']) == _machine).toList();
    return hit.isEmpty ? '' : s(hit.first['typical']);
  }

  void _pickMachine() {
    final ms = _machines;
    _machine = ms.isEmpty ? null : s(ms.first['id']);
  }

  Future<void> _send() async {
    setState(() {
      _busy = true;
      _error = null;
    });
    try {
      final r = m(await Api.post('/api/reports', {
        'user_id': s(Api.user?['id']),
        'site_id': _site,
        'machine_id': _machine,
        'symptom': _text.text.trim(),
        'severity': _sev,
        'manual': _manual,
        'source': 'app',
        if (_photo != null) 'photo': _photo,
        if (!_manual && _plan != null) 'accept_after': _plan,
      }));
      _text.clear();
      if (!mounted) return;
      widget.onSent();
      await Navigator.of(context).push(MaterialPageRoute(builder: (_) => TrackScreen(reportId: s(r['id']))));
    } on ApiError catch (e) {
      setState(() => _error = e.message);
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    if (_meta == null) return Center(child: _error != null ? Text(_error!, style: const TextStyle(color: C.red)) : const CircularProgressIndicator(color: C.violet));
    return ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 28), children: [
      const Padding(padding: EdgeInsets.fromLTRB(4, 8, 4, 4), child: Text('Report a problem', style: TextStyle(fontSize: 28, fontWeight: FontWeight.w800, letterSpacing: -0.8))),
      const Padding(
        padding: EdgeInsets.fromLTRB(4, 0, 4, 16),
        child: Text('We offer it to the closest technician who has actually fixed this kind of fault before.', style: TextStyle(color: C.mute, height: 1.4)),
      ),
      DropdownButtonFormField<String>(
        initialValue: _site,
        isExpanded: true,
        dropdownColor: C.s2,
        decoration: const InputDecoration(labelText: 'Site'),
        items: [for (final x in l(_meta!['sites'])) DropdownMenuItem(value: s(m(x)['id']), child: Text('${s(m(x)['name'])} · ${s(m(x)['area'])}', overflow: TextOverflow.ellipsis))],
        onChanged: (v) => setState(() {
          _site = v;
          _pickMachine();
        }),
      ),
      const SizedBox(height: 12),
      DropdownButtonFormField<String>(
        key: ValueKey(_site),
        initialValue: _machine,
        isExpanded: true,
        dropdownColor: C.s2,
        decoration: const InputDecoration(labelText: 'Unit'),
        items: [for (final x in _machines) DropdownMenuItem(value: s(x['id']), child: Text('${s(x['id'])} · ${s(x['model'])} · ${s(x['location'])}', overflow: TextOverflow.ellipsis))],
        onChanged: (v) => setState(() => _machine = v),
      ),
      const SizedBox(height: 14),
      const Text('HOW URGENT', style: TextStyle(color: C.mute, fontSize: 11.5, fontWeight: FontWeight.w800, letterSpacing: 1.2)),
      const SizedBox(height: 8),
      SegmentedButton<String>(
        segments: const [
          ButtonSegment(value: 'normal', label: Text('Normal')),
          ButtonSegment(value: 'high', label: Text('High')),
          ButtonSegment(value: 'urgent', label: Text('Urgent')),
        ],
        selected: {_sev},
        onSelectionChanged: (v) => setState(() => _sev = v.first),
      ),
      const SizedBox(height: 14),
      const Text('MODE', style: TextStyle(color: C.mute, fontSize: 11.5, fontWeight: FontWeight.w800, letterSpacing: 1.2)),
      const SizedBox(height: 8),
      SegmentedButton<bool>(
        segments: const [
          ButtonSegment(value: false, label: Text('Demo')),
          ButtonSegment(value: true, label: Text('Manual')),
        ],
        selected: {_manual},
        onSelectionChanged: (v) => setState(() => _manual = v.first),
      ),
      const SizedBox(height: 6),
      Text(
        _manual
            ? 'Manual: nobody answers by themselves. A real technician on a phone, or the presenter on the dispatch screen, accepts or rejects.'
            : 'Demo: the other technicians answer by themselves, so the whole story plays on its own.',
        style: const TextStyle(color: C.mute, fontSize: 12.5, height: 1.4),
      ),
      if (!_manual) ...[
        const SizedBox(height: 12),
        const Text('WHO ACCEPTS', style: TextStyle(color: C.mute, fontSize: 11.5, fontWeight: FontWeight.w800, letterSpacing: 1.2)),
        const SizedBox(height: 8),
        Wrap(spacing: 8, runSpacing: 8, children: [
          for (final o in const [(null, 'Random'), (0, 'First request'), (3, 'After 3'), (7, 'After 7'), (12, 'After 12'), (-1, 'Nobody')])
            ChoiceChip(label: Text(o.$2), selected: _plan == o.$1, onSelected: (_) => setState(() => _plan = o.$1)),
        ]),
        if ((_plan ?? 0) >= 4) const Padding(padding: EdgeInsets.only(top: 6), child: Text('Brings in the 30-technician city fleet so that many can answer.', style: TextStyle(color: C.mute, fontSize: 12.5))),
      ],
      const SizedBox(height: 14),
      TextField(controller: _text, maxLines: 4, minLines: 3, decoration: const InputDecoration(labelText: 'What is wrong', hintText: 'e.g. Outdoor unit keeps tripping and the floor is not cooling')),
      if (_typical.isNotEmpty)
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: () => setState(() => _text.text = _typical),
            icon: const Icon(Icons.auto_fix_high_rounded, size: 18, color: C.violet2),
            label: const Text('Use a typical description for this unit', style: TextStyle(color: C.violet2)),
          ),
        ),
      const SizedBox(height: 14),
      if (_photo == null)
        OutlinedButton.icon(onPressed: _pickPhoto, icon: const Icon(Icons.photo_camera_outlined), label: const Text('Add a photo of the unit (optional)'))
      else
        Stack(children: [
          unitPhoto(_photo),
          Positioned(top: 22, right: 8, child: IconButton.filledTonal(onPressed: () => setState(() => _photo = null), icon: const Icon(Icons.close_rounded))),
        ]),
      const Padding(
        padding: EdgeInsets.only(top: 6),
        child: Text('Optional, but a photo of the unit or its error display helps the technician arrive prepared.', style: TextStyle(color: C.mute, fontSize: 12.5, height: 1.4)),
      ),
      if (_error != null) ...[
        const SizedBox(height: 12),
        Panel(color: const Color(0xFF2E1018), border: const Color(0xFF7A2638), child: Text(_error!, style: const TextStyle(color: C.red))),
      ],
      const SizedBox(height: 18),
      FilledButton.icon(onPressed: _busy ? null : _send, icon: _busy ? const _Spin() : const Icon(Icons.send_rounded), label: const Text('Send it to the best technician')),
    ]);
  }
}

class MyReportsScreen extends StatefulWidget {
  const MyReportsScreen({super.key});

  @override
  State<MyReportsScreen> createState() => _MyReportsScreenState();
}

class _MyReportsScreenState extends State<MyReportsScreen> {
  List<dynamic> _rows = const [];
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _load();
    _timer = Timer.periodic(const Duration(seconds: 3), (_) => _load());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _load() async {
    try {
      final r = l(await Api.get('/api/reports?user_id=${Uri.encodeComponent(s(Api.user?['id']))}'));
      if (mounted) setState(() => _rows = r);
    } catch (_) {}
  }

  @override
  Widget build(BuildContext context) => ListView(padding: const EdgeInsets.fromLTRB(16, 4, 16, 24), children: [
        const Padding(padding: EdgeInsets.fromLTRB(4, 8, 4, 14), child: Text('My reports', style: TextStyle(fontSize: 28, fontWeight: FontWeight.w800, letterSpacing: -0.8))),
        if (_rows.isEmpty)
          const Panel(child: Text('Nothing reported yet. Report a problem and follow it here.', style: TextStyle(color: C.mute, height: 1.45))),
        for (final r in _rows)
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Panel(
              onTap: () => Navigator.of(context).push(MaterialPageRoute(builder: (_) => TrackScreen(reportId: s(m(r)['id'])))),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Row(children: [StatusPill(s(m(r)['status'])), const Spacer(), Text(s(m(r)['id']), style: const TextStyle(color: C.dim, fontSize: 12))]),
                const SizedBox(height: 10),
                Text(s(m(r)['symptom']), style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w600, height: 1.35)),
                const SizedBox(height: 6),
                Text(s(m(r)['site']), style: const TextStyle(color: C.mute, fontSize: 13)),
                if (m(r)['assigned'] != null) ...[
                  const SizedBox(height: 6),
                  Text('${s(m(m(r)['assigned'])['name'])} · ETA ${s(m(r)['eta_min'])} min', style: const TextStyle(color: C.cyan, fontSize: 13, fontWeight: FontWeight.w600)),
                ],
              ]),
            ),
          ),
      ]);
}

class _OtpCard extends StatelessWidget {
  final String otp;
  const _OtpCard({required this.otp});

  @override
  Widget build(BuildContext context) => Panel(
        color: C.deep,
        border: C.violet,
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          const Text('YOUR OTP', style: TextStyle(color: C.violet2, fontSize: 11.5, fontWeight: FontWeight.w800, letterSpacing: 1.2)),
          const SizedBox(height: 8),
          Text(otp.split('').join('  '), style: const TextStyle(fontSize: 40, fontWeight: FontWeight.w800, letterSpacing: 6)),
          const SizedBox(height: 8),
          const Text('Give this code to the technician only when they arrive and are ready to start. They cannot start the work, or close the job, without it.', style: TextStyle(color: C.mute, height: 1.45)),
        ]),
      );
}

class StatusPill extends StatelessWidget {
  final String status;
  const StatusPill(this.status, {super.key});

  @override
  Widget build(BuildContext context) {
    const names = {'offered': 'Finding a technician', 'en_route': 'On the way', 'on_site': 'Arrived', 'working': 'Working', 'resolved': 'Resolved', 'unassigned': 'Needs a manager'};
    const colors = {'offered': C.amber, 'en_route': C.cyan, 'on_site': C.violet2, 'working': C.violet2, 'resolved': C.ok, 'unassigned': C.red};
    return Pill(names[status] ?? status, color: colors[status] ?? C.mute);
  }
}

// ============================================================ follow a report, like following a ride
class TrackScreen extends StatefulWidget {
  final String reportId;
  const TrackScreen({super.key, required this.reportId});

  @override
  State<TrackScreen> createState() => _TrackScreenState();
}

class _TrackScreenState extends State<TrackScreen> {
  Map<String, dynamic>? _r;
  Timer? _timer;
  String? _error;

  @override
  void initState() {
    super.initState();
    _poll();
    _timer = Timer.periodic(const Duration(milliseconds: 1500), (_) => _poll());
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  Future<void> _poll() async {
    try {
      final r = m(await Api.get('/api/reports/${widget.reportId}?viewer=${Uri.encodeComponent(s(Api.user?['id']))}'));
      if (!mounted) return;
      setState(() => _r = r);
      if (s(r['status']) == 'resolved' || s(r['status']) == 'unassigned') _timer?.cancel();
    } on ApiError catch (e) {
      if (mounted) setState(() => _error = e.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final r = _r;
    return Scaffold(
      appBar: AppBar(title: Text(widget.reportId)),
      body: r == null
          ? Center(child: _error != null ? Text(_error!, style: const TextStyle(color: C.red)) : const CircularProgressIndicator(color: C.violet))
          : ListView(padding: const EdgeInsets.fromLTRB(16, 0, 16, 32), children: [
              Panel(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  Row(children: [StatusPill(s(r['status'])), const SizedBox(width: 8), Pill(s(r['severity']), color: s(r['severity']) == 'urgent' ? C.red : (s(r['severity']) == 'high' ? C.amber : C.cyan))]),
                  const SizedBox(height: 12),
                  Text(s(r['symptom']), style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w700, height: 1.35)),
                  const SizedBox(height: 8),
                  Text('${s(r['site'])}${r['machine'] != null ? ' · ${s(m(r['machine'])['id'])} ${s(m(r['machine'])['model'])}' : ''}', style: const TextStyle(color: C.mute)),
                ]),
              ),
              const SizedBox(height: 14),
              _hero(r),
              if (r['counts'] != null && ((m(r['counts'])['notified'] as num?) ?? 0) > 0) ...[const SizedBox(height: 14), _Counts(c: m(r['counts']))],
              if (r['otp'] != null) ...[const SizedBox(height: 14), _OtpCard(otp: s(r['otp']))],
              const SizedBox(height: 14),
              Panel(
                child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                  const Text('WHY THIS PRIORITY', style: TextStyle(color: C.mute, fontSize: 11.5, fontWeight: FontWeight.w800, letterSpacing: 1.2)),
                  const SizedBox(height: 8),
                  Wrap(spacing: 6, runSpacing: 6, children: [for (final x in l(m(r['priority'])['reasons'])) Pill(s(x), color: C.violet2)]),
                ]),
              ),
              const SizedBox(height: 14),
              const Text('WHAT HAPPENED', style: TextStyle(color: C.mute, fontSize: 11.5, fontWeight: FontWeight.w800, letterSpacing: 1.2)),
              const SizedBox(height: 8),
              for (final e in l(r['events']).reversed)
                Container(
                  margin: const EdgeInsets.only(bottom: 8),
                  padding: const EdgeInsets.all(12),
                  decoration: BoxDecoration(color: C.s2, borderRadius: BorderRadius.circular(14), border: const Border(left: BorderSide(color: C.violet, width: 3))),
                  child: Text(s(m(e)['text']), style: const TextStyle(height: 1.4)),
                ),
            ]),
    );
  }

  Widget _hero(Map<String, dynamic> r) {
    final st = s(r['status']);
    final a = r['assigned'] == null ? null : m(r['assigned']);
    final offer = r['offer'] == null ? null : m(r['offer']);
    if (st == 'offered') {
      return Panel(
        color: const Color(0xFF241B08),
        border: const Color(0xFF7A5A12),
        child: Row(children: [
          const SizedBox(width: 22, height: 22, child: CircularProgressIndicator(strokeWidth: 2.4, color: C.amber)),
          const SizedBox(width: 14),
          Expanded(
            child: Text(
              offer != null
                  ? (((offer['count'] as num?) ?? 1) > 1
                      ? 'Layer ${s(r['wave'])}: notifying ${s(offer['count'])} technicians${offer['ring_km'] != null ? ' within ${s(offer['ring_km'])} km' : ''} at once. Waiting for answers (${s(offer['expires_in'])}s)…'
                      : 'Layer ${s(r['wave'])}: asking ${s(offer['name'])}. Waiting for an answer (${s(offer['expires_in'])}s)…')
                  : 'Finding the best technician…',
              style: const TextStyle(fontSize: 15.5, height: 1.4),
            ),
          ),
        ]),
      );
    }
    if (st == 'unassigned') {
      return const Panel(color: Color(0xFF2E1018), border: Color(0xFF7A2638), child: Text('Nobody could take it just now. The service manager has been told and will assign someone.', style: TextStyle(height: 1.45)));
    }
    final prog = (r['progress'] as num?)?.toDouble() ?? 0;
    return Panel(
      color: st == 'resolved' ? const Color(0xFF0A2A1F) : C.deep,
      border: st == 'resolved' ? const Color(0xFF136B4B) : C.violet,
      child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
        if (r['confirmed'] == true && st != 'resolved')
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Row(children: [
              const Icon(Icons.verified_rounded, color: C.ok, size: 20),
              const SizedBox(width: 8),
              Text('CONFIRMED${a == null ? '' : ': ${s(a['name']).split(' ').first} accepted'}', style: const TextStyle(color: C.ok, fontWeight: FontWeight.w800, letterSpacing: 1)),
            ]),
          ),
        if (st == 'resolved')
          Padding(
            padding: const EdgeInsets.only(bottom: 12),
            child: Row(children: [
              Icon(s(r['outcome']) == 'not_done' ? Icons.replay_rounded : Icons.check_circle_rounded, color: s(r['outcome']) == 'not_done' ? C.amber : C.ok, size: 20),
              const SizedBox(width: 8),
              Text(s(r['outcome']) == 'not_done' ? 'NOT DONE' : 'WORK DONE', style: TextStyle(color: s(r['outcome']) == 'not_done' ? C.amber : C.ok, fontWeight: FontWeight.w800, letterSpacing: 1)),
            ]),
          ),
        Row(children: [
          CircleAvatar(radius: 24, backgroundColor: C.s3, child: Text(a == null ? '?' : s(a['name']).substring(0, 1), style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w800))),
          const SizedBox(width: 14),
          Expanded(
            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
              Text(a == null ? '' : s(a['name']), style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800)),
              Text(a == null ? '' : s(a['speciality']), style: const TextStyle(color: C.mute, fontSize: 13)),
            ]),
          ),
          if (st == 'en_route') Text('ETA ${s(r['eta_min'])} min', style: const TextStyle(color: C.cyan, fontWeight: FontWeight.w800)),
        ]),
        const SizedBox(height: 14),
        if (st == 'en_route') ClipRRect(borderRadius: BorderRadius.circular(99), child: LinearProgressIndicator(value: prog, minHeight: 8, color: C.cyan, backgroundColor: C.s3)),
        if (st == 'en_route') const SizedBox(height: 8),
        Text(
          st == 'en_route'
              ? 'On the way to you.'
              : (st == 'on_site' ? 'Arrived. Give them your OTP so they can start.' : (st == 'working' ? 'OTP verified. The work is in progress.' : (s(r['outcome']) == 'not_done' ? 'Not done. The technician could not fix it this time, and a revisit is needed.' : 'Work done. The fix has been recorded so the next visit is faster.'))),
          style: const TextStyle(height: 1.4),
        ),
      ]),
    );
  }
}


/// Rapido-style tally of how the technicians answered.
class _Counts extends StatelessWidget {
  final Map<String, dynamic> c;
  const _Counts({required this.c});

  Widget _cell(Object? n, String label, Color col) => Expanded(
        child: Column(children: [
          Text('${n ?? 0}', style: TextStyle(fontSize: 26, fontWeight: FontWeight.w800, color: col)),
          Text(label, style: const TextStyle(color: C.mute, fontSize: 10.5, fontWeight: FontWeight.w700, letterSpacing: 1)),
        ]),
      );

  @override
  Widget build(BuildContext context) => Panel(
        child: Row(children: [
          _cell(c['notified'], 'NOTIFIED', C.text),
          _cell(c['declined'], 'REJECTED', C.red),
          _cell(c['accepted'], 'ACCEPTED', C.ok),
          _cell(c['waiting'], 'WAITING', C.amber),
        ]),
      );
}
