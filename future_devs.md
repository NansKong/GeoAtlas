# Future Development Plans (Post-MVP)

This document contains features, plans, and architectural requirements for GeoAtlas that have been postponed from the current MVP. These features will be revisited once the free full-stack web platform is completed and stable.

---

## 1. Monetization & Subscriptions

*Currently, the platform is 100% free with unlimited access. These are the plans for future subscription tiers and paywalls.*

### Planned Tiers
| Tier | Price | Features |
|------|-------|---------|
| Free | $0 | Basic news feed, 5 predictions/day, 3 boards |
| Pro | $12–20/month | Full predictions, unlimited boards, alerts, advanced analytics |
| Institutional | $100–500/month | API access, bulk data export, custom feeds |

### Implementation Tasks
- [ ] Integrate Stripe for subscription payments.
- [ ] Implement Free tier limits (enforce quota on predictions and intelligence boards).
- [ ] Implement Pro tier logic (grant full predictions, unlimited boards, advanced alerts).
- [ ] Implement Institutional tier API (rate-limited API key access generation and billing).

---

## 2. Mobile Application

*Currently, the platform focuses strictly on the web-based Next.js frontend. The mobile app initiative should resume once the web platform is feature-complete.*

### Tech Stack
- Frontend Framework: React Native + Expo
- Language: TypeScript
- Target: Single codebase for iOS and Android platforms

### Scope & Features
- Real-time geopolitical event feed.
- Asset watchlist tracking with market prices.
- Intelligence board management (drag and drop pins).
- Native Alert Center.
- Mobile push alerts (integrating Firebase FCM for push notifications).

### Implementation Tasks
- [ ] Initialize the React Native + Expo project.
- [ ] Build the core data fetching mechanisms reusing backend `/modules` endpoints.
- [ ] Build the primary UI flows (Event Feed, Watchlist, Boards, Alert Settings).
- [ ] Configure and test Firebase FCM for mobile push notifications.
- [ ] Setup iOS and Android build pipelines via EAS (Expo Application Services).
