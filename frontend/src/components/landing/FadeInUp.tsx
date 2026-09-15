"use client";

import React from "react";
import { motion } from "framer-motion";

interface FadeInUpProps {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}

export default function FadeInUp({
  children,
  delay = 0,
  className = "",
}: FadeInUpProps) {
  return (
    <motion.div
      initial={{ opacity: 0, y: 40 }} // translate-y-10 is 40px (2.5rem)
      whileInView={{ opacity: 1, y: 0 }}
      viewport={{ once: true, margin: "-60px" }}
      transition={{
        duration: 1.0, // 1000ms
        delay,
        ease: [0.16, 1, 0.3, 1], // premium cubic bezier
      }}
      className={className}
    >
      {children}
    </motion.div>
  );
}

export { FadeInUp };
