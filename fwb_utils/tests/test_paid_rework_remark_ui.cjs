const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const { test } = require('node:test');

function setup(values = {}) {
    const handlers = {};
    const dialogs = [];
    const messages = [];
    const frappe = {
        validated: true,
        msgprint: (message) => messages.push(message),
        ui: {
            form: { on: (doctype, events) => Object.assign(handlers, events) },
            Dialog: class {
                constructor(options) { this.options = options; dialogs.push(this); }
                show() { this.shown = true; }
                hide() { this.shown = false; this.options.onhide?.(); }
            },
        },
    };
    const filename = path.join(__dirname, '../fwb_manufacturing/doctype/fwb_work_report/fwb_work_report.js');
    vm.runInNewContext(fs.readFileSync(filename, 'utf8'), { frappe }, { filename });
    const frm = {
        doc: { name: 'new-report', docstatus: 0, rework_type: '有偿返工', remark: '', ...values },
        toggle_reqd(fieldname, required) { this.required = required; },
        async set_value(fieldname, value) { this.doc[fieldname] = value; },
    };
    return { handlers, dialogs, messages, frappe, frm };
}

test('selecting paid rework prompts for a mandatory remark at every station', () => {
    for (const workstation of ['木工房', '裱纸区', '贴皮区', '底漆房', '面漆房', '装配区', '抛光区', '软包区', '其它工位']) {
        const { handlers, dialogs, frm } = setup({ workstation });
        handlers.rework_type(frm);
        assert.equal(frm.required, true);
        assert.equal(dialogs.length, 1);
        assert.equal(dialogs[0].shown, true);
        assert.equal(dialogs[0].options.fields[0].reqd, 1);
    }
});

test('canceling a prompt cannot bypass validation and only one dialog opens', () => {
    const { handlers, dialogs, frm, frappe } = setup();
    handlers.rework_type(frm);
    handlers.validate(frm);
    assert.equal(frappe.validated, false);
    assert.equal(dialogs.length, 1);
    dialogs[0].hide();
    handlers.validate(frm);
    assert.equal(dialogs.length, 2);
    assert.equal(frappe.validated, false);
});

test('whitespace is rejected and a valid reason is written to the original remark', async () => {
    const { handlers, dialogs, messages, frm, frappe } = setup();
    handlers.rework_type(frm);
    await dialogs[0].options.primary_action({ remark: ' \n\t　' });
    assert.equal(frm.doc.remark, '');
    assert.equal(dialogs[0].shown, true);
    assert.equal(messages.length, 1);
    await dialogs[0].options.primary_action({ remark: '  客户改色，重新喷漆  ' });
    assert.equal(frm.doc.remark, '客户改色，重新喷漆');
    assert.equal(dialogs[0].shown, false);
    frappe.validated = true;
    handlers.validate(frm);
    assert.equal(frappe.validated, true);
});

test('normal, unpaid, already noted and submitted reports do not prompt', () => {
    for (const values of [{ rework_type: '否' }, { rework_type: '无偿返工' },
        { remark: '已有返工原因' }, { docstatus: 1 }, { docstatus: 2 }]) {
        const { handlers, dialogs, frm } = setup(values);
        handlers.refresh(frm);
        handlers.rework_type(frm);
        assert.equal(dialogs.length, 0);
    }
});

test('switching back to normal production removes mandatory state and closes the prompt', () => {
    const { handlers, dialogs, frm } = setup();
    handlers.rework_type(frm);
    frm.doc.rework_type = '否';
    handlers.rework_type(frm);
    assert.equal(frm.required, false);
    assert.equal(dialogs[0].shown, false);
});

test('a stale prompt never writes a reason to another report or another rework type', async () => {
    for (const values of [{ name: 'another-report' }, { rework_type: '否' }]) {
        const { handlers, dialogs, frm } = setup();
        handlers.rework_type(frm);
        Object.assign(frm.doc, values);
        await dialogs[0].options.primary_action({ remark: '旧弹窗内容' });
        assert.equal(frm.doc.remark, '');
        assert.equal(dialogs[0].shown, false);
    }
});
