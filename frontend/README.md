# InstaDL - Frontend

This is the static frontend for InstaDL, ready to be deployed on Vercel.

## Deployment on Vercel

1. Push this `frontend` directory to a GitHub repository or use Vercel CLI directly.
2. If using Vercel CLI, simply run:
   ```bash
   npm i -g vercel
   vercel
   ```
3. The project is already configured with `vercel.json` to handle clean URLs (e.g., `/about` maps to `/about.html`) and set appropriate security and caching headers.

## Configuration

If you change your backend API URL, simply update the `API_BASE_URL` in `js/config.js`:

```javascript
const CONFIG = {
    API_BASE_URL: "https://api.instadl.com"
};
```
