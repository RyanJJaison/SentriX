import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import NotFound from "@/pages/NotFound";
import { Redirect, Route, Switch, useLocation } from "wouter";
import { isAuthenticated } from "@/lib/api";
import { useEffect, useRef, useState } from "react";
import ErrorBoundary from "./components/ErrorBoundary";
import { ThemeProvider } from "./contexts/ThemeContext";
import { SmoothScrollProvider, PageTransition } from "@/components/motion";
import Home from "./pages/Home";
import Login from "./pages/Login";
import Platform from "./pages/Platform";
import CaseStudy from "./pages/CaseStudy";

/**
 * Gate for authenticated-only routes.
 *
 * Presence of a token in the key api.ts owns ("sentrix_token") is deliberately
 * the whole check: the backend validates the JWT on every request and api.ts
 * clears the stored token on a 401, so an expired token surfaces as a redirect
 * on the next API call rather than being parsed here. Decoding expiry
 * client-side is a possible later improvement, not a requirement.
 *
 * wouter's `Redirect` navigates from a layout effect and renders null, so this
 * performs no side effect during render and still goes through the app's own
 * router (and therefore its page-transition handling).
 */
function RequireAuth({ children }: { children: React.ReactNode }) {
  if (!isAuthenticated()) return <Redirect to="/login" replace />;
  return <>{children}</>;
}

function Router() {
  const [location, navigate] = useLocation();

  return (
    <PageTransition location={location} navigate={navigate}>
      <Switch>
        <Route path="/" component={Home} />
        {/* `path` stays on the Route itself: the wouter patch enumerates
            Switch children by element.props.path to build __WOUTER_ROUTES__. */}
        <Route path="/platform">{() => <RequireAuth><Platform /></RequireAuth>}</Route>
        <Route path="/works/:slug">{(params) => <CaseStudy slug={params.slug} />}</Route>
        <Route path="/login" component={Login} />
        <Route path="/404" component={NotFound} />
        <Route component={NotFound} />
      </Switch>
    </PageTransition>
  );
}

function App() {
  return (
    <ErrorBoundary>
      <ThemeProvider defaultTheme="dark">
        <TooltipProvider>
          <SmoothScrollProvider>
            <Toaster />
            <Router />
          </SmoothScrollProvider>
        </TooltipProvider>
      </ThemeProvider>
    </ErrorBoundary>
  );
}

export default App;
