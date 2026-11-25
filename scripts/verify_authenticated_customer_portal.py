"""Disposable, local-only HTTPS browser proof for authenticated customer portal."""
import base64
import hashlib
import secrets
import os
import ssl
import subprocess
import tempfile
import threading
from socketserver import ThreadingMixIn
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

def main():
    if os.environ.get('DJANGO_SETTINGS_MODULE') not in (None, 'jireh.schools.test_settings'):
        raise RuntimeError('Disposable settings required')
    os.environ['DJANGO_SETTINGS_MODULE'] = 'jireh.schools.test_settings'
    from django.conf import settings
    from django.core.management import call_command

    with tempfile.TemporaryDirectory(prefix='jireh-portal-rehearsal-') as root:
        root = Path(root)
        rp = 'director.jireh.test'
        settings.SECRET_KEY = secrets.token_urlsafe(48)
        settings.DATABASES = {'default': {'ENGINE':'django.db.backends.sqlite3','NAME':str(root/'fictional.sqlite3')}}
        settings.ROOT_URLCONF = 'jireh.runtime.customer_portal_urls'
        settings.ALLOWED_HOSTS = [rp]
        settings.TEMPLATES = [{'BACKEND':'django.template.backends.django.DjangoTemplates','APP_DIRS':True}]
        for flag in ('JIREH_CUSTOMER_PORTAL_ACCEPTANCE','JIREH_CUSTOMER_CORE_ACCEPTANCE','JIREH_CUSTOMER_FAMILY_SESSION_ACCEPTANCE','JIREH_CUSTOMER_ONBOARDING_ACCEPTANCE','JIREH_CUSTOMER_DIRECTOR_SESSION_ACCEPTANCE','JIREH_DIRECTOR_WEBAUTHN_ACCEPTANCE','SESSION_COOKIE_SECURE','SESSION_COOKIE_HTTPONLY','CSRF_COOKIE_SECURE','CSRF_COOKIE_HTTPONLY','SECURE_SSL_REDIRECT'):
            setattr(settings,flag,True)
        for flag in ('JIREH_SYNTHETIC_SUBMISSION_ONLY','JIREH_SYNTHETIC_DOCUMENTS_ONLY','JIREH_SYNTHETIC_APPLICATION_REVIEW','JIREH_SYNTHETIC_QUESTIONNAIRE_STORAGE','JIREH_CUSTOMER_WORKSPACE_ACCEPTANCE','JIREH_CUSTOMER_EXTERNAL_IDENTITY_ACCEPTANCE','JIREH_OPERATOR_CREDENTIAL_RECOVERY_ENABLED','DEBUG'):
            setattr(settings,flag,False)
        settings.JIREH_DIRECTOR_WEBAUTHN_RP_ID = rp
        import django
        django.setup()
        from django.core.wsgi import get_wsgi_application
        from django.contrib.auth import get_user_model
        from jireh.schools.models import AcademicYear, Student, HouseholdAccess
        from jireh.schools.services import link_student_to_household
        from jireh.schools.invitations import issue_household_invitation
        from jireh.schools.redemption import issue_mailbox_challenge
        from jireh.financial_aid.models import AidApplicationStudent
        from django.urls import reverse
        from jireh.financial_aid import test_customer_director_sessions as fixture_module
        from jireh.financial_aid.test_customer_director_sessions import DirectorSessionTests, CREDENTIAL_ID, PASSWORD
        fixture_module.RP = rp
        from cryptography.hazmat.primitives import serialization
        from cryptography import x509
        from playwright.sync_api import sync_playwright, expect
        call_command('migrate',verbosity=0)
        f = SimpleNamespace()
        DirectorSessionTests.setUp(f)
        year = AcademicYear.objects.create(school=f.school,name='2027-28',start_date=date(2027,8,1),end_date=date(2028,6,30))
        child = Student.objects.create(school=f.school,first_name='Fictional',last_name='Child')
        link_student_to_household(school_id=f.school.pk,household_id=f.household.pk,student_id=child.pk)
        new = get_user_model().objects.create_user(username='portal-browser-new',password=PASSWORD)
        _, invite = issue_household_invitation(actor=f.actor,school_id=f.school.pk,household_id=f.household.pk,email='browser@example.invalid')
        _, mailbox = issue_mailbox_challenge(user=new,email='browser@example.invalid')
        cert, key = root/'cert.pem', root/'key.pem'
        subprocess.run(['openssl','req','-x509','-newkey','rsa:2048','-nodes','-days','1','-subj',f'/CN={rp}','-addext',f'subjectAltName=DNS:{rp}','-keyout',str(key),'-out',str(cert)],check=True,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
        app = get_wsgi_application()
        def https(environ,start_response):
            environ['wsgi.url_scheme']='https'
            environ['HTTPS']='on'
            return app(environ,start_response)
        class Quiet(WSGIRequestHandler):
            def log_message(self,fmt,*args):
                pass
        class ThreadedServer(ThreadingMixIn, WSGIServer):
            daemon_threads = True

        server = make_server('127.0.0.1', 0, https, server_class=ThreadedServer, handler_class=Quiet)
        tls=ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        tls.load_cert_chain(cert,key)
        key.chmod(0o600)
        public_key = x509.load_pem_x509_certificate(cert.read_bytes()).public_key()
        spki = public_key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
        pin = base64.b64encode(hashlib.sha256(spki).digest()).decode('ascii')
        server.socket=tls.wrap_socket(server.socket,server_side=True)
        thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
        try:
            with sync_playwright() as p:
                browser=p.chromium.launch(headless=True,args=['--no-proxy-server',
                    f'--host-resolver-rules=MAP {rp}:443 127.0.0.1:{server.server_port}, MAP * ~NOTFOUND',
                    f'--ignore-certificate-errors-spki-list={pin}'])
                context=browser.new_context(service_workers='block')
                context.route('**/*', lambda route: route.continue_() if route.request.url.startswith('https://' + rp + '/') else route.abort())
                page=context.new_page(); errors=[]; page.on('pageerror',lambda error:errors.append(str(error)))
                origin='https://'+rp
                assert page.goto(origin+'/customer/').status == 200
                assert page.evaluate('window.isSecureContext')
                expect(page.get_by_role('heading',name='Secure financial aid access')).to_be_visible()
                form=page.locator('section').filter(has=page.get_by_role('heading',name='First household invitation'))
                form.get_by_label('Username').fill(new.username);form.get_by_label('Password').fill(PASSWORD);form.get_by_role('button',name='Continue to invitation').click()
                expect(page.get_by_role('heading',name='Redeem your first household invitation')).to_be_visible(timeout=15000)
                family_url = origin + reverse('jireh_workspace_family', args=(f.school.pk, f.household.pk, year.pk))
                director_url = origin + reverse('jireh_workspace_director', args=(f.school.pk, year.pk))
                assert page.goto(family_url).status == 403
                page.goto(origin + '/customer/')
                page.get_by_label('School reference').fill(str(f.school.pk));page.get_by_label('Household reference').fill(str(f.household.pk));page.get_by_label('Invitation proof').fill(invite);page.get_by_label('Mailbox proof').fill(mailbox);page.get_by_role('button',name='Redeem invitation').click()
                expect(page.get_by_role('heading',name='Family sign-in')).to_be_visible(timeout=15000)
                assert HouseholdAccess.objects.filter(user=new,household=f.household,is_active=True).exists()
                print('PASS: browser restricted invitation and dual-proof redemption',flush=True)
                form=page.locator('section').filter(has=page.get_by_role('heading',name='Family sign-in'))
                form.get_by_label('Username').fill(new.username);form.get_by_label('Password').fill(PASSWORD);form.get_by_role('button',name='Sign in',exact=True).click()
                expect(page.get_by_role('heading',name='Your workspace')).to_be_visible(timeout=15000)
                page.get_by_role('link',name='Fictional family — Fictional A · 2027-28').click()
                expect(page.get_by_text('No draft exists for this year.')).to_be_visible();page.get_by_role('button',name='Create annual draft').click()
                expect(page.get_by_text('DRAFT — saved')).to_be_visible(timeout=15000)
                page.get_by_role('button',name='Include Fictional').click();expect(page.get_by_text('1 selected')).to_be_visible(timeout=15000)
                assert AidApplicationStudent.objects.filter(application__academic_year=year).count()==1
                expect(page.get_by_text('Open financial questionnaire')).to_have_count(0)
                assert page.goto(director_url).status == 403
                page.goto(origin + '/customer/')
                page.get_by_role('button',name='Sign out').click();expect(page.get_by_role('heading',name='Family sign-in')).to_be_visible(timeout=15000)
                print('PASS: browser family sign-in, draft creation, selection, persisted readback and logout',flush=True)
                form=page.locator('section').filter(has=page.get_by_role('heading',name='School director sign-in'))
                form.get_by_label('School reference').fill(str(f.school.pk));form.get_by_label('Username').fill(f.actor.username);form.get_by_label('Password').fill(PASSWORD);form.get_by_role('button',name='Continue to security key').click()
                expect(page.get_by_role('heading',name='Verify your security key')).to_be_visible(timeout=15000)
                assert page.goto(director_url).status == 403
                page.goto(origin + '/customer/')
                cdp=context.new_cdp_session(page);cdp.send('WebAuthn.enable')
                auth=cdp.send('WebAuthn.addVirtualAuthenticator',{'options':{'protocol':'ctap2','transport':'usb','hasResidentKey':False,'hasUserVerification':True,'isUserVerified':True,'automaticPresenceSimulation':True}})['authenticatorId']
                private=f.key.private_bytes(serialization.Encoding.DER,serialization.PrivateFormat.PKCS8,serialization.NoEncryption())
                cdp.send('WebAuthn.addCredential',{'authenticatorId':auth,'credential':{'credentialId':base64.b64encode(CREDENTIAL_ID).decode(),'isResidentCredential':False,'rpId':rp,'privateKey':base64.b64encode(private).decode(),'signCount':0}})
                page.get_by_role('button',name='Verify security key').click()
                expect(page.get_by_role('heading',name='Your workspace')).to_be_visible(timeout=15000)
                page.get_by_role('link',name='Fictional A · 2027-28').click();expect(page.get_by_role('heading',name='Director workload')).to_be_visible()
                expect(page.locator('#draft-total')).to_have_text('1');expect(page.locator('#child-total')).to_have_text('1')
                page.get_by_role('link',name='Open case').click();expect(page.locator('#case-child-count')).to_have_text('1')
                expect(page.get_by_text('Record fictional',exact=False)).to_have_count(0)
                assert not errors,errors
                f.credential.refresh_from_db();assert f.credential.sign_count>0
                other = origin + reverse('jireh_workspace_director', args=(f.other_school.pk, f.other_year.pk))
                assert page.goto(other).status == 403
                assert page.goto(family_url).status == 403
                f.grant.is_active = False
                f.grant.save(update_fields=['is_active', 'updated_at'])
                assert page.goto(director_url).status == 403
                page.goto(origin + '/customer/')
                print('PASS: browser director password, actual virtual WebAuthn signed assertion, session, workload and same draft case',flush=True)
                page.get_by_role('button',name='Sign out').click();expect(page.get_by_role('heading',name='School director sign-in')).to_be_visible(timeout=15000)
                browser.close()
        finally:
            server.shutdown();server.server_close();thread.join(timeout=5)


if __name__ == '__main__':
    main()
