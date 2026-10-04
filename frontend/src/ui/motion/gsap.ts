import { gsap } from 'gsap';
import { CustomEase } from 'gsap/CustomEase';
import { SplitText } from 'gsap/SplitText';
import { ScrambleTextPlugin } from 'gsap/ScrambleTextPlugin';
import { DrawSVGPlugin } from 'gsap/DrawSVGPlugin';
import { Flip } from 'gsap/Flip';

// Register all GSAP plugins once
if (typeof window !== 'undefined') {
  gsap.registerPlugin(CustomEase, SplitText, ScrambleTextPlugin, DrawSVGPlugin, Flip);
  CustomEase.create('interlock', '0.22, 1, 0.36, 1');
  CustomEase.create('snap', '0.7, 0, 0.2, 1');
  // lock ease with ~8% overshoot
  CustomEase.create('lock', 'M0,0 C0.12,0.6 0.3,1.08 1,1');
}

export { gsap, CustomEase, SplitText, ScrambleTextPlugin, DrawSVGPlugin, Flip };
export default gsap;
