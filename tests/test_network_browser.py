# SPDX-License-Identifier: LGPL-3.0-only
"""Real Odoo web-client coverage, usable with Community or Enterprise assets."""

import base64
import json
import shutil
import socket
import subprocess
import tempfile
import time
from contextlib import contextmanager
from itertools import pairwise
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from odoo.tests import HttpCase, tagged
from odoo.tests.common import TEST_CURSOR_COOKIE_NAME, _preexec, flushing_cursor


@tagged("post_install", "-at_install")
class TestNetworkBrowser(HttpCase):
    def test_network_journey_and_editor(self):
        self.env.ref("base.user_admin").lang = "en_US"
        people = self.env["res.partner"].create(
            [
                {"name": "Network browser " + name, "personal_crm_contact": True}
                for name in ["Anna", "Peter", "Maria", "David"]
            ]
        )
        kind = self.env.ref("personal_crm.relationship_type_friend")
        links = self.env["personal.crm.relationship"]
        for left, right in pairwise(people):
            links.create(
                {
                    "left_partner_id": left.id,
                    "right_partner_id": right.id,
                    "type_id": kind.id,
                }
            )
        links.create(
            {
                "left_partner_id": people[0].id,
                "right_partner_id": people[1].id,
                "type_id": self.env.ref("personal_crm.relationship_type_sibling").id,
            }
        )
        code = r"""
(async () => {
    const ids = PEOPLE;
    const wait = async (fn, label) => {
        for (let i=0;i<200;i++) { if(fn()) return; await new Promise(r=>setTimeout(r,50)); }
        throw new Error('Timed out: '+label+'; '+document.body.innerText.slice(-1500));
    };
    const check=(value,label)=>{if(!value)throw new Error(label);};
    const action=odoo.__WOWL_DEBUG__.root.env.services.action;
    const button=(text, root=document)=>[...root.querySelectorAll('button')].find(b=>b.textContent.trim()===text);
    const click=async(text,root=document)=>{await wait(()=>button(text,root),text);button(text,root).click();await new Promise(r=>setTimeout(r,200));};
    await action.doAction({type:'ir.actions.client',tag:'personal_crm.network',name:'Network',params:{partnerId:ids[0]}});
    await wait(()=>document.querySelectorAll('[data-node]').length===3,'dedicated depth two');
    check(document.querySelector('.pcrm_toolbar').textContent.includes('Anna'),'focal contact');
    document.querySelector(`[data-node="${ids[2]}"]`).dispatchEvent(new MouseEvent('click',{bubbles:true}));
    await wait(()=>document.querySelectorAll('[data-node]').length===4,'manual expansion');
    check(document.querySelector('.pcrm_toolbar').textContent.includes('Anna'),'expansion retains focus');
    await click('Focus here',document.querySelector('.pcrm_inspector'));
    await wait(()=>document.querySelector('.pcrm_toolbar').textContent.includes('Maria'),'explicit focus');
    await click('Back');
    await wait(()=>document.querySelector('.pcrm_toolbar').textContent.includes('Anna'),'history restores focus');
    await click('Full network');
    await wait(()=>document.querySelector('.pcrm_status').textContent.includes('Full network complete'),'full complete');
    await click('Back');
    await wait(()=>!document.querySelector('.pcrm_status').textContent.includes('Full network complete'),'back restores bounded');
    document.querySelector('[data-connection]').dispatchEvent(new MouseEvent('click',{bubbles:true}));
    await wait(()=>document.querySelector('.pcrm_inspector article'),'group inspection');
    await click('Add relationships',document.querySelector('.pcrm_toolbar'));
    await wait(()=>document.querySelector('.o_dialog #pcrm_add_type'),'batch dialog');
    check(document.querySelector('.o_dialog').textContent.includes('Anna'),'focal contact prefilled');
    await click('Cancel',document.querySelector('.o_dialog'));
    await wait(()=>!document.querySelector('.o_dialog'),'batch cancelled');
    const transfer=new DataTransfer();
    document.querySelector(`[data-node="${ids[0]}"] [draggable]`).dispatchEvent(new DragEvent('dragstart',{bubbles:true,dataTransfer:transfer}));
    document.querySelector(`[data-node="${ids[3]}"]`).dispatchEvent(new DragEvent('drop',{bubbles:true,cancelable:true,dataTransfer:transfer}));
    await wait(()=>document.querySelector('.o_dialog #pcrm_add_type'),'drag creation dialog');
    const editor=document.querySelector('.o_dialog');
    check(editor.textContent.includes('Anna') && editor.textContent.includes('David'),'drag participants prefilled');
    const type=editor.querySelector('#pcrm_add_type');
    type.value=[...type.options].find(option=>option.textContent==='Sibling').value;
    type.dispatchEvent(new Event('change',{bubbles:true}));
    await wait(()=>!editor.querySelector('.btn-primary[disabled]'),'batch ready');
    type.value=[...type.options].find(option=>option.textContent==='Parent / Child').value;
    type.dispatchEvent(new Event('change',{bubbles:true}));
    check(editor.textContent.includes('David'),'type change retains selected contact');
    type.value=[...type.options].find(option=>option.textContent==='Sibling').value;
    type.dispatchEvent(new Event('change',{bubbles:true}));
    await wait(()=>!editor.querySelector('.btn-primary[disabled]'),'batch ready after type change');
    await click('Add 1 relationship',editor);
    await wait(()=>!document.querySelector('.o_dialog') && document.querySelector('.pcrm_status').textContent.includes('5 relationship records'),'saved connection refresh');
    await click('End relationship',document.querySelector('.pcrm_inspector'));
    await wait(()=>document.querySelector('.o_dialog input[type="date"]'),'end date dialog');
    await click('Save end date',document.querySelector('.o_dialog'));
    await wait(()=>!document.querySelector('.o_dialog'),'end saved');
    check(document.querySelector('.pcrm_status').textContent.includes('5 relationship records'),'inclusive end date remains current');
    await click('Archive',document.querySelector('.pcrm_inspector'));
    await wait(()=>document.querySelector('.pcrm_status').textContent.includes('4 relationship records'),'archive refresh');
    await action.doAction({type:'ir.actions.act_window',res_model:'res.partner',res_id:ids[0],views:[[false,'form']],context:{form_view_ref:'personal_crm.person_form',personal_crm_navigation:true}});
    await wait(()=>document.querySelector('.o_form_view'),'contact form');
    check(!document.querySelector('.o_pcrm_embedded'),'network stays unmounted on first tab');
    [...document.querySelectorAll('.o_notebook .nav-link')].find(el=>el.textContent.trim()==='Network').click();
    await wait(()=>document.querySelector('.o_pcrm_embedded [data-node]'),'embedded viewer');
    check(document.querySelectorAll('.o_pcrm_embedded [data-node]').length===2,'inline depth one');
    document.querySelector(`.o_pcrm_embedded [data-node="${ids[1]}"]`).dispatchEvent(new MouseEvent('click',{bubbles:true}));
    await wait(()=>document.querySelectorAll('.o_pcrm_embedded [data-node]').length===3,'inline expands in place');
    check(document.querySelector('.o_form_view'),'contact form preserved');
    await click('Add relationships',document.querySelector('.o_pcrm_embedded .pcrm_toolbar'));
    await wait(()=>document.querySelector('.o_dialog #pcrm_add_type'),'embedded batch dialog');
    await click('Cancel',document.querySelector('.o_dialog'));
    await wait(()=>!document.querySelector('.o_dialog'),'dialog cancelled');
    await click('Continue in dedicated viewer');
    await wait(()=>document.querySelector('.o_pcrm_network_action [data-node]'),'continue action');
    check(document.querySelectorAll('[data-node]').length===3,'continuation retains depth-one exploration');
    console.log('test successful');
})();
""".replace("PEOPLE", json.dumps(people.ids))
        self.network_browser_js(
            "/odoo?debug=1",
            code,
            ready="odoo.isReady === true",
            login="admin",
            timeout=120,
        )

    def network_browser_js(self, url_path, code, ready, login, timeout):
        """Use Odoo's runner, or installed ChromeDriver when websocket-client is absent."""
        from odoo.tests.common import websocket

        if websocket is not None:
            return self.browser_js(
                url_path, code, ready=ready, login=login, timeout=timeout
            )
        if not shutil.which("chromedriver"):
            self.skipTest("Browser tests require websocket-client or ChromeDriver")
        self.env.flush_all()
        with (
            self.allow_requests(all_requests=True),
            flushing_cursor(self.cr),
            self.network_chromedriver() as request,
        ):
            self.authenticate(login, login)
            request("POST", "/url", {"url": self.base_url() + "/web/health"})
            request(
                "POST",
                "/cookie",
                {
                    "cookie": {
                        "name": "session_id",
                        "value": self.session.sid,
                        "path": "/",
                    }
                },
            )
            request(
                "POST",
                "/cookie",
                {
                    "cookie": {
                        "name": TEST_CURSOR_COOKIE_NAME,
                        "value": self.http_request_key,
                        "path": "/",
                    }
                },
            )
            request("POST", "/url", {"url": self.base_url() + url_path})
            request("POST", "/timeouts", {"script": timeout * 1000})
            result = request(
                "POST",
                "/execute/async",
                {
                    "script": """
                    const [code,ready,done]=arguments;
                    (async()=>{
                        for(let i=0;i<200;i++) {
                            if (document.querySelector('.o_module_error_banner')) throw new Error('Module loading failed: '+JSON.stringify([...odoo.loader.failed]));
                            try { if(eval(ready))return await eval(code); } catch(error) {
                                if (error instanceof ReferenceError) {} else throw error;
                            }
                            await new Promise(r=>setTimeout(r,100));
                        }
                        throw new Error('Odoo did not become ready: '+document.body.innerText.slice(-2000)+'; '+JSON.stringify({ready:odoo.isReady,failed:[...odoo.loader.failed],jobs:[...odoo.loader.jobs],apps:[...odoo.loader.modules.get('@odoo/owl').App.apps].map(a=>({status:a.pluginManager.status,plugins:Object.entries(a.pluginManager.plugins).map(([id,p])=>({id,status:p.status}))}))}));
                    })().then(()=>done({ok:true}),error=>done({error:error.stack||String(error)}));
                """,
                    "args": [code, ready],
                },
            )
            if result.get("error"):
                screenshot = request("GET", "/screenshot")
                Path("/tmp/pcrm-network-browser.png").write_bytes(
                    base64.b64decode(screenshot)
                )
                result["error"] += "\nBrowser logs: " + json.dumps(
                    request("POST", "/log", {"type": "browser"})[-30:]
                )
            self.assertTrue(result.get("ok"), result.get("error"))

    @contextmanager
    def network_chromedriver(self):
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        with tempfile.TemporaryFile() as log:
            process = subprocess.Popen(
                ["chromedriver", f"--port={port}"],
                stdout=log,
                stderr=log,
                preexec_fn=_preexec,  # noqa: PLW1509 - same Chrome memory-limit reset as Odoo's runner
            )
            session_id = None

            def request(method, path, body=None):
                prefix = f"/session/{session_id}" if session_id else ""
                data = json.dumps(body).encode() if body is not None else None
                req = Request(
                    f"http://127.0.0.1:{port}{prefix}{path}",
                    data=data,
                    method=method,
                    headers={"Content-Type": "application/json"},
                )
                with urlopen(req, timeout=180) as response:
                    return json.load(response)["value"]

            try:
                for _ in range(100):
                    if process.poll() is not None:
                        log.seek(0)
                        raise AssertionError(
                            "ChromeDriver exited: "
                            + log.read().decode(errors="replace")
                        )
                    try:
                        request("GET", "/status")
                        break
                    except URLError:
                        time.sleep(0.1)
                result = request(
                    "POST",
                    "/session",
                    {
                        "capabilities": {
                            "alwaysMatch": {
                                "browserName": "chrome",
                                "goog:loggingPrefs": {"browser": "ALL"},
                                "goog:chromeOptions": {
                                    "binary": shutil.which("chromium")
                                    or shutil.which("google-chrome"),
                                    "args": [
                                        "--headless=new",
                                        "--no-sandbox",
                                        "--disable-dev-shm-usage",
                                        "--window-size=1440,1000",
                                        "--no-proxy-server",
                                    ],
                                },
                            }
                        }
                    },
                )
                session_id = result["sessionId"]
                yield request
            finally:
                if session_id:
                    request("DELETE", "")
                process.terminate()
                process.wait(timeout=10)
