import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import NotFound from "@/pages/NotFound";
import { Route, Switch, useLocation } from "wouter";
import { useEffect, useRef, useState } from "react";
import ErrorBoundary from "./components/ErrorBoundary";
import { ThemeProvider } from "./contexts/ThemeContext";
import { SmoothScrollProvider, PageTransition } from "@/components/motion";
import Home from "./pages/Home";
import Login from "./pages/Login";
import Platform from "./pages/Platform";
import CaseStudy from "./pages/CaseStudy";

function Router() {
  const [location, navigate] = useLocation();

  return (
    <PageTransition location={location} navigate={navigate}>
      <Switch>
        <Route path="/" component={Home} />
        <Route path="/platform" component={Platform} />
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
