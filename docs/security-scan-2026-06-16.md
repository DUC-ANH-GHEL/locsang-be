# Bao cao security scan Loc Sang - 2026-06-16

Pham vi scan: `locsang-be` va `locsang-fe` trong `D:\LocSang`.

Ket luan ngan: **chua the coi la an toan de public production**. Hien co nhieu diem co the bi khai thac that su, trong do nghiem trong nhat la cac endpoint ghi/xoa du lieu khong can dang nhap, token reset mat khau co the bi tra ve client neu production dung default, va secret mac dinh/hardcoded trong source.

## Muc do uu tien

### P0 - Can xu ly ngay

1. **Legacy user API cho thao tac user khong can dang nhap**
   - Evidence:
     - `app/main.py:69` mount `api_router` tai `/api/v1`.
     - `app/presentation/api/v1/api.py:8` include `user_routes`.
     - `app/presentation/api/v1/endpoints/users.py:79`, `:107`, `:123`, `:140` co `POST /users/`, `GET /users/{user_id}`, `PUT /users/{user_id}`, `DELETE /users/{user_id}` nhung khong co `Depends(get_current_user)`.
   - Rui ro: attacker co the doc/sua/xoa user, doi password, role, trang thai tai khoan.
   - Fix de xuat: chi giu `/api/v1/users/login` va `/api/v1/users/verify-token`; tat ca route user con lai phai bo khoi production hoac them admin guard. DTO public khong duoc cho set `role_id`, `is_active`.

2. **Public product API cho tao/sua/xoa san pham khong can dang nhap**
   - Evidence:
     - `app/main.py:73` mount `public_api_router` tai `/api`.
     - `app/presentation/api/public_api/api.py:16` include `products_router`.
     - `app/presentation/api/public_api/endpoints/products.py:803`, `:865`, `:927` co `POST /api/products`, `PUT /api/products/{id}`, `DELETE /api/products/{id}` nhung chi depend `get_db`.
   - Rui ro: attacker co the tao/sua/an san pham tren storefront.
   - Fix de xuat: public products chi read-only. Chuyen mutation sang admin router, hoac them admin guard va test anonymous phai tra 401/403.

3. **Legacy category API cho tao/sua/xoa danh muc khong can dang nhap**
   - Evidence:
     - `app/presentation/api/v1/api.py:9` include `category_routes`.
     - `app/presentation/api/v1/endpoints/categories.py:26`, `:77`, `:99` co `POST/PUT/DELETE` nhung khong auth.
   - Rui ro: attacker co the pha catalog/danh muc.
   - Fix de xuat: bo write route legacy `/api/v1/categories` hoac them admin guard; public category chi read-only.

4. **Hardcoded Gemini API key va proxy Gemini khong auth**
   - Evidence:
     - `app/presentation/api/v1/api.py:11` mount `gemini_routes`.
     - `app/presentation/api/v1/endpoints/gemini.py:14` hardcode API key.
     - `app/presentation/api/v1/endpoints/gemini.py:17` endpoint `POST /api/v1/gemini/ask` khong auth/rate limit.
   - Rui ro: bi lay key, abuse quota/billing, hoac dung backend lam proxy.
   - Fix de xuat: rotate key ngay, xoa key khoi source, dua vao env/secret manager, them auth/rate limit hoac go endpoint neu khong dung.

### P1 - High

5. **Default `SECRET_KEY` trong source**
   - Evidence: `app/core/config.py:19` dat `SECRET_KEY = "your-secret-key-here"`.
   - Rui ro: neu env production thieu `SECRET_KEY`, attacker co the ky JWT hop le.
   - Fix de xuat: khong co default cho production; fail startup khi secret thieu/placeholder; rotate secret sau khi fix.

6. **Forgot password co the tra reset token ra response theo default**
   - Evidence:
     - `app/core/config.py:26` dat `AUTH_DEBUG_EXPOSE_PASSWORD_RESET_TOKEN = True`.
     - `app/presentation/api/public_api/endpoints/accounts.py:399-401` gan `reset_token` va `reset_url` vao response khi flag bat.
   - Rui ro: biet email khach la co the xin token reset mat khau neu deploy dung default.
   - Fix de xuat: default `False`; production fail startup neu flag bat; chi gui link qua email.

7. **Khach co the claim don guest chi bang so dien thoai**
   - Evidence:
     - `app/presentation/api/public_api/endpoints/accounts.py:518-545` gan `order.user_id = user.id` neu phone match.
     - `app/presentation/api/public_api/endpoints/accounts.py:548-555` goi claim trong `GET /api/account/orders`.
   - Rui ro: nguoi khac biet so dien thoai co the claim va xem/huy don pending cua khach.
   - Fix de xuat: khong mutate trong GET; claim order can tracking code + phone, OTP, hoac claim token tu checkout.

8. **Admin login open redirect sau khi da luu token**
   - Evidence:
     - `locsang-fe/src/pages/admin/Login.tsx:101-102` doc `redirect` tu query.
     - `locsang-fe/src/pages/admin/Login.tsx:104-109` luu token vao storage.
     - `locsang-fe/src/pages/admin/Login.tsx:118` gan thang `window.location.href = redirectUrl`.
   - Rui ro: link login doc hai co the dieu huong admin sang URL khong tin cay sau khi login.
   - Fix de xuat: chi cho redirect path noi bo bat dau bang `/admin`; chan `http:`, `https:`, `javascript:`, `//`; dung `navigate(safePath, { replace: true })`.

9. **Token admin/storefront luu trong Web Storage**
   - Evidence:
     - `locsang-fe/src/services/apiClient.ts:5`, `:47` doc va gui `adminToken`.
     - `locsang-fe/src/services/customerAccountService.ts:93-104` doc/luu storefront token.
   - Rui ro: bat ky XSS nao cung co the lay token.
   - Fix de xuat: chuyen auth sang HttpOnly Secure SameSite cookie + CSRF; neu chua doi ngay thi tat remember default, dung sessionStorage ngan han va token rotation.

10. **Dependency frontend con advisory nghiem trong**
    - Evidence: `npm audit --omit=dev --audit-level=moderate` bao 13 vulnerabilities, gom 1 critical, 7 high.
    - Goi can uu tien: `axios`, `react-router-dom`/`@remix-run/router`, `form-data`, `serve`.
    - Fix de xuat: update lock/dependency, chay `npm audit` lai va smoke test login/admin/storefront.

### P2 - Medium

11. **Login endpoint in credential object va access token ra log**
    - Evidence: `app/presentation/api/v1/endpoints/users.py:24`, `:28`, `:62`.
    - Rui ro: nguoi doc log co the thay password object/token.
    - Fix de xuat: xoa print, dung structured logging co redaction.

12. **CORS qua rong voi credential**
    - Evidence: `app/main.py:44-47` allow regex moi subdomain `*.cgnn.vn`, credentials, methods/headers `*`.
    - Rui ro: subdomain bi takeover hoac app phu bi compromise co the goi API trong ngu canh tin cay.
    - Fix de xuat: chi allow origin chinh xac can dung: `https://locsang.cgnn.vn`, domain admin neu tach rieng, localhost dev qua env.

13. **Notification URL khong bi gioi han same-origin/admin path**
    - Evidence:
      - `locsang-fe/public/sw.js:149`, `:179-189`.
      - `locsang-fe/src/components/layout/Header.tsx:75`, `:176`.
    - Rui ro: neu notification payload/record bi thao tung, admin click thong bao co the bi dua sang domain/path khong mong muon.
    - Fix de xuat: normalize bang `new URL(value, origin)`, chi chap nhan same-origin va path `/admin/...`.

14. **Rich text dung sanitizer thu cong va chua co CSP**
    - Evidence:
      - `locsang-fe/src/pages/client/ProductDetail.jsx:516`.
      - `locsang-fe/src/pages/admin/Product/ProductReadonlyDetail.tsx:509`.
      - `locsang-fe/vercel.json` chua co security headers/CSP.
    - Rui ro: neu sanitizer drift/bypass, token Web Storage co the bi lay.
    - Fix de xuat: dung sanitizer tap trung nhu DOMPurify voi allowlist; them test payload XSS; them CSP (`object-src 'none'`, `base-uri 'self'`, `frame-ancestors 'none'`, `script-src` phu hop).

## Diem da on hon

- Chua thay SQL injection ro rang trong luong duoc scan; code dung ORM/bind params.
- Upload Cloudinary cua admin co guard admin va size cap; tuy nhien nen tra loi loi generic, khong expose exception noi bo.
- `.env`/`.env.local` khong nam trong tracked git theo `git ls-files`, nhung co secret backend dang nam trong workspace FE local; nen tach va rotate secret da tung dat o do.
- Google login da duoc go khoi source FE theo grep hien tai, khong con import `@react-oauth/google`.

## Verification da chay

- Backend: `python -m compileall app alembic` pass.
- Frontend: `npm audit --omit=dev --audit-level=moderate` fail do con vulnerabilities.
- Sub-agent read-only da audit rieng backend va frontend; ket qua da duoc doi chieu voi grep/code evidence tren.

## Thu tu fix de xuat

1. Dong ngay cac write route public/legacy: `/api/v1/users/*`, `/api/v1/categories/*`, `POST/PUT/DELETE /api/products`.
2. Rotate Gemini key, dua vao env, va go/tat proxy neu khong dung.
3. Bat buoc `SECRET_KEY` production, tat `AUTH_DEBUG_EXPOSE_PASSWORD_RESET_TOKEN`.
4. Fix open redirect admin login va notification URL allowlist.
5. Doi token storage sang HttpOnly cookie hoac giam rui ro tam thoi bang sessionStorage/TTL ngan.
6. Sua claim guest order bang co che tracking code/OTP.
7. Update dependency va them CSP.

