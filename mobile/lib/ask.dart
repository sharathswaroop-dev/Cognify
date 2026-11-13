import 'package:flutter/material.dart';

import 'api.dart';
import 'jobs.dart';
import 'theme.dart';

class _Msg {
  final String role; // user | assistant
  final String text;
  final String kind;
  final List<String> chips;
  final Map<String, dynamic>? offer;
  final int sources;
  _Msg(this.role, this.text, {this.kind = 'answer', this.chips = const [], this.offer, this.sources = 0});
}

/// Talk to the company memory like a colleague. It greets, asks what is wrong when the problem is vague, answers from past repairs with the
/// records behind it, and learns from a correction typed in plain words.
class AskScreen extends StatefulWidget {
  /// Set while the technician is on a job: the chat then knows which unit they are working on.
  final String? machineId;
  final String? jobLabel;
  const AskScreen({super.key, this.machineId, this.jobLabel});

  @override
  State<AskScreen> createState() => _AskScreenState();
}

class _AskScreenState extends State<AskScreen> {
  final _ctl = TextEditingController();
  final _scroll = ScrollController();
  final List<_Msg> _msgs = [
    _Msg('assistant', 'Hi. Tell me what is going on with your equipment, or ask what the team has learned before.', kind: 'chat'),
  ];
  bool _busy = false;

  static const _jobChips = ['What failed on this unit before?', 'What should I check first?', 'Which parts do I need?'];

  @override
  void didUpdateWidget(AskScreen old) {
    super.didUpdateWidget(old);
    if (widget.machineId != null && widget.machineId != old.machineId) {
      setState(() => _msgs.add(_Msg('assistant', 'You are on ${widget.machineId}${widget.jobLabel == null ? '' : ' at ${widget.jobLabel}'}. Ask me anything about this unit, or tell me what you find and I will remember it.', kind: 'chat', chips: _jobChips)));
      _toEnd();
    }
  }

  @override
  void dispose() {
    _ctl.dispose();
    _scroll.dispose();
    super.dispose();
  }

  void _toEnd() => WidgetsBinding.instance.addPostFrameCallback((_) {
        if (_scroll.hasClients) _scroll.animateTo(_scroll.position.maxScrollExtent, duration: const Duration(milliseconds: 250), curve: Curves.easeOut);
      });

  Future<void> _send(String text) async {
    final t = text.trim();
    if (t.isEmpty || _busy) return;
    final history = _msgs.length <= 1
        ? <Map<String, dynamic>>[]
        : _msgs.skip(1).toList().reversed.take(10).toList().reversed.map((x) => {'role': x.role, 'content': x.text, 'kind': x.role == 'assistant' ? x.kind : null}).toList();
    setState(() {
      _msgs.add(_Msg('user', t));
      _busy = true;
    });
    _ctl.clear();
    _toEnd();
    try {
      final r = m(await Api.post('/api/chat', {'message': t, 'context': null, 'deep': false, 'history': history, if (widget.machineId != null) 'machine_id': widget.machineId}));
      setState(() => _msgs.add(_Msg(
            'assistant',
            s(r['answer']),
            kind: s(r['kind']),
            chips: l(r['chips']).map(s).toList(),
            offer: r['offer'] is Map ? m(r['offer']) : null,
            sources: l(r['sources']).length,
          )));
    } on ApiError catch (e) {
      setState(() => _msgs.add(_Msg('assistant', e.message, kind: 'error')));
    } finally {
      if (mounted) setState(() => _busy = false);
      _toEnd();
    }
  }

  Future<void> _openJob(String machineId) async {
    try {
      final jobs = l(await Api.get('/api/jobs/open'));
      final hit = jobs.map(m).where((j) => s(j['machine_id']) == machineId).toList();
      if (!mounted) return;
      if (hit.isEmpty) {
        ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('No open job for $machineId.')));
        return;
      }
      Navigator.of(context).push(MaterialPageRoute(builder: (_) => JobScreen(job: hit.first)));
    } on ApiError catch (e) {
      if (mounted) ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text(e.message)));
    }
  }

  @override
  Widget build(BuildContext context) => Column(children: [
        if (widget.machineId != null)
          Padding(
            padding: const EdgeInsets.fromLTRB(14, 0, 14, 4),
            child: Panel(
              color: C.deep,
              border: C.violet,
              padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
              child: Row(children: [
                const Icon(Icons.build_circle_rounded, color: C.violet2),
                const SizedBox(width: 10),
                Expanded(child: Text('Working on ${widget.machineId}${widget.jobLabel == null ? '' : ' · ${widget.jobLabel}'}', style: const TextStyle(fontWeight: FontWeight.w700))),
              ]),
            ),
          ),
        Expanded(
          child: ListView.builder(
            controller: _scroll,
            padding: const EdgeInsets.fromLTRB(14, 8, 14, 12),
            itemCount: _msgs.length + (_busy ? 1 : 0),
            itemBuilder: (_, i) {
              if (i >= _msgs.length) return const _Typing();
              final msg = _msgs[i];
              return _Bubble(
                msg: msg,
                isLast: i == _msgs.length - 1,
                onChip: _send,
                onOffer: (mid) => _openJob(mid),
              );
            },
          ),
        ),
        SafeArea(
          top: false,
          child: Padding(
            padding: const EdgeInsets.fromLTRB(12, 6, 12, 10),
            child: Row(children: [
              Expanded(
                child: TextField(
                  controller: _ctl,
                  minLines: 1,
                  maxLines: 4,
                  textInputAction: TextInputAction.send,
                  onSubmitted: _send,
                  decoration: const InputDecoration(hintText: 'Describe the problem, or tell me what you fixed…', contentPadding: EdgeInsets.symmetric(horizontal: 16, vertical: 12)),
                ),
              ),
              const SizedBox(width: 8),
              IconButton.filled(
                onPressed: _busy ? null : () => _send(_ctl.text),
                style: IconButton.styleFrom(backgroundColor: C.violet, foregroundColor: Colors.white),
                icon: const Icon(Icons.arrow_upward_rounded),
              ),
            ]),
          ),
        ),
      ]);
}

class _Bubble extends StatelessWidget {
  final _Msg msg;
  final bool isLast;
  final ValueChanged<String> onChip;
  final ValueChanged<String> onOffer;
  const _Bubble({required this.msg, required this.isLast, required this.onChip, required this.onOffer});

  @override
  Widget build(BuildContext context) {
    final mine = msg.role == 'user';
    final learned = msg.kind == 'corrected' || msg.kind == 'saved';
    final err = msg.kind == 'error';
    return Align(
      alignment: mine ? Alignment.centerRight : Alignment.centerLeft,
      child: Container(
        margin: const EdgeInsets.symmetric(vertical: 5),
        constraints: BoxConstraints(maxWidth: MediaQuery.of(context).size.width * 0.86),
        padding: const EdgeInsets.all(14),
        decoration: BoxDecoration(
          color: mine ? C.violet : (learned ? const Color(0xFF0A2A1F) : (err ? const Color(0xFF2E1018) : C.s2)),
          borderRadius: BorderRadius.only(
            topLeft: const Radius.circular(18),
            topRight: const Radius.circular(18),
            bottomLeft: Radius.circular(mine ? 18 : 4),
            bottomRight: Radius.circular(mine ? 4 : 18),
          ),
          border: Border.all(color: mine ? C.violet : (learned ? const Color(0xFF136B4B) : (err ? const Color(0xFF7A2638) : C.line))),
        ),
        child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
          if (learned)
            const Padding(
              padding: EdgeInsets.only(bottom: 6),
              child: Row(mainAxisSize: MainAxisSize.min, children: [
                Icon(Icons.check_circle_rounded, size: 16, color: C.ok),
                SizedBox(width: 6),
                Text('LEARNED', style: TextStyle(color: C.ok, fontSize: 11.5, fontWeight: FontWeight.w800, letterSpacing: 1.1)),
              ]),
            ),
          Text(msg.text, style: TextStyle(fontSize: 15, height: 1.45, color: err ? C.red : C.text)),
          if (!mine && msg.kind == 'answer' && msg.sources > 0) ...[
            const SizedBox(height: 8),
            Text('${msg.sources} records retrieved', style: const TextStyle(color: C.dim, fontSize: 12)),
          ],
          if (isLast && msg.chips.isNotEmpty) ...[
            const SizedBox(height: 10),
            Wrap(spacing: 8, runSpacing: 8, children: [
              for (final c in msg.chips) ActionChip(label: Text(c), backgroundColor: C.s3, side: const BorderSide(color: C.line2), onPressed: () => onChip(c)),
            ]),
          ],
          if (msg.offer != null && s(msg.offer!['scenario_id']).isNotEmpty) ...[
            const SizedBox(height: 10),
            FilledButton.icon(
              onPressed: () => onOffer(s(msg.offer!['machine_id'])),
              icon: const Icon(Icons.hub_rounded, size: 18),
              label: Text('Run the four agents on ${s(msg.offer!['machine_id'])}'),
              style: FilledButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 10)),
            ),
          ],
        ]),
      ),
    );
  }
}

class _Typing extends StatelessWidget {
  const _Typing();

  @override
  Widget build(BuildContext context) => const Align(
        alignment: Alignment.centerLeft,
        child: Padding(
          padding: EdgeInsets.all(12),
          child: SizedBox(width: 38, height: 14, child: LinearProgressIndicator(color: C.violet, backgroundColor: C.s3, borderRadius: BorderRadius.all(Radius.circular(8)))),
        ),
      );
}
