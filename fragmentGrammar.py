from utilities import *

from task import *
from fragmentUtilities import *
from frontier import *
from grammar import *
from program import *

from itertools import izip
import gc

import time

class FragmentGrammar(object):
    def __init__(self, logVariable, productions):
        self.logVariable = logVariable
        self.productions = productions
        self.likelihoodCache = {}

    def clearCache(self):
        self.likelihoodCache = {}

    def __repr__(self):
        return "FragmentGrammar(logVariable={self.logVariable}, productions={self.productions}".format(self=self)
    def __str__(self):
        def productionKey((l,t,p)):
            return not isinstance(p,Primitive), -l
        return "\n".join(["%f\tt0\t$_"%self.logVariable] + \
                         [ "%f\t%s\t%s"%(l,t,p) for l,t,p in sorted(self.productions, key = productionKey) ])
                                                                    

    def buildCandidates(self, context, environment, request):
        candidates = []
        variableCandidates = []
        for l,t,p in self.productions:
            try:
                newContext, t = t.instantiate(context)
                newContext = newContext.unify(t.returns(), request)
                candidates.append((l,newContext,
                                   t.apply(newContext),
                                   p))
            except UnificationFailure: continue
        for j,t in enumerate(environment):
            try:
                newContext = context.unify(t.returns(), request)
                variableCandidates.append((newContext,
                                           t.apply(newContext),
                                           Index(j)))
            except UnificationFailure: continue
        if variableCandidates:
            z = math.log(len(variableCandidates))
            for newContext, newType, index in variableCandidates:
                candidates.append((self.logVariable - z, newContext, newType, index))

        z = lse([candidate[0] for candidate in candidates])
        return [(l - z, c, t, p) for l, c, t, p in candidates]

    def logLikelihood(self, request, expression):
        _,l,_ = self._logLikelihood(Context.EMPTY, [], request, expression)
        if invalid(l):
            f = 'failures/likelihoodFailure%s.pickle'%(time() + getPID())
            eprint("PANIC: Invalid log likelihood. expression:",expression,"tp:",request,"Exported to:",f)
            with open(f,'wb') as handle:
                pickle.dump((self,request, expression),handle)
            assert False
        return l

    def closedUses(self, request, expression):
        _,l,u = self._logLikelihood(Context.EMPTY, [], request, expression)
        return l,u

    def _logLikelihood(self, context, environment, request, expression):
        '''returns (context, log likelihood, uses)'''

        # We can cash likelihood calculations faster whenever they don't involve type inference
        # This is because they are guaranteed to not modify the context, 
        polymorphic = request.isPolymorphic or any(v.isPolymorphic for v in environment)
        # For some reason polymorphic caching slows it down
        shouldDoCaching = not polymorphic
        shouldDoCaching = False

        # Caching
        if shouldDoCaching:
            if polymorphic:
                inTypes = canonicalTypes([request.apply(context)] + [ v.apply(context) for v in environment])
            else:
                inTypes = canonicalTypes([request] + environment)
            cacheKey = (tuple(inTypes), expression)
            if cacheKey in self.likelihoodCache:
                outTypes, l, u = self.likelihoodCache[cacheKey]
                context, instantiatedTypes = instantiateTypes(context, outTypes)
                outRequest = instantiatedTypes[0]
                outEnvironment = instantiatedTypes[1:]
                # eprint("request:", request.apply(context), "environment:",
                #        [ v.apply(context) for v in environment ])
                # eprint("will be unified with: out request:",outRequest,"out environment",outEnvironment)
                if polymorphic:
                    context = context.unify(request, outRequest)
                    for v,vp in zip(environment, outEnvironment):
                        context = context.unify(v, vp)                
                return context,l,u            
        
        if request.isArrow():
            if not isinstance(expression,Abstraction):
                return (context,NEGATIVEINFINITY,Uses.empty)
            return self._logLikelihood(context,
                                      [request.arguments[0]] + environment,
                                      request.arguments[1],
                                      expression.body)
        
        # Not a function type

        # Construct and normalize the candidate productions
        candidates = self.buildCandidates(context, environment, request)

        # Consider each way of breaking the expression up into a
        # function and arguments
        totalLikelihood = NEGATIVEINFINITY
        weightedUses = []

        possibleVariables = float(int(any(isinstance(candidate,Index)
                                          for _,_,_,candidate in candidates )))
        possibleUses = {candidate: 1. for _,_,_,candidate in candidates
                                      if not isinstance(candidate,Index)}
        
        for f,xs in expression.applicationParses():
            for candidateLikelihood, newContext, tp, production in candidates:
                variableBindings = {}
                # This is a variable in the environment
                if production.isIndex:
                    if production != f: continue
                else:
                    try:
                        newContext, fragmentType, variableBindings = \
                                            Matcher.match(newContext, production, f, len(xs))
                        # This is necessary because the types of the variable
                        # bindings and holes need to match up w/ request
                        fragmentTypeTemplate = request
                        for _ in xs:
                            newContext, newVariable = newContext.makeVariable()
                            fragmentTypeTemplate = arrow(newVariable, fragmentTypeTemplate)
                        newContext = newContext.unify(fragmentType, fragmentTypeTemplate)
                        # update the unified type
                        tp = fragmentType.apply(newContext)
                    except MatchFailure: continue

                argumentTypes = tp.functionArguments()
                if len(xs) != len(argumentTypes):
                    # I think that this is some kind of bug. But I can't figure it out right now.
                    # As a hack, count this as though it were a failure
                    continue
                    #raise GrammarFailure('len(xs) != len(argumentTypes): tp={}, xs={}'.format(tp, xs))


                thisLikelihood = candidateLikelihood
                if isinstance(production, Index):
                    theseUses = Uses(possibleVariables=possibleVariables,
                                     actualVariables=1.,
                                     possibleUses=possibleUses.copy(),
                                     actualUses={})
                else:
                    theseUses = Uses(possibleVariables=possibleVariables,
                                     actualVariables=0.,
                                     possibleUses=possibleUses.copy(),
                                     actualUses={production: 1.})

                # Accumulate likelihood from free variables and holes and arguments
                for freeType,freeExpression in variableBindings.values() + zip(argumentTypes, xs):
                    freeType = freeType.apply(newContext)
                    newContext, expressionLikelihood, newUses = \
                            self._logLikelihood(newContext, environment, freeType, freeExpression)
                    if expressionLikelihood is NEGATIVEINFINITY:
                        thisLikelihood = NEGATIVEINFINITY
                        break
                    
                    thisLikelihood += expressionLikelihood
                    theseUses += newUses

                if thisLikelihood is NEGATIVEINFINITY: continue

                weightedUses.append((thisLikelihood,theseUses))
                totalLikelihood = lse(totalLikelihood, thisLikelihood)

                # Any of these new context objects should be equally good
                context = newContext

        if totalLikelihood is NEGATIVEINFINITY:
            print "total likelihood is negative infinity"
            print request, expression
            print environment
            return context, totalLikelihood, Uses.empty
        assert weightedUses != []

        allUses = Uses.join(totalLikelihood, *weightedUses)

        # memoize result
        if shouldDoCaching:
            outTypes = [ request.apply(context) ] + [ v.apply(context) for v in environment ]
            outTypes = canonicalTypes(outTypes)
            self.likelihoodCache[cacheKey] = (outTypes, totalLikelihood, allUses)

        return context, totalLikelihood, allUses

    def expectedUses(self, frontiers):
        likelihoods = [ [ (l + entry.logLikelihood, u)
                         for entry in frontier
                         for l,u in [self.closedUses(frontier.task.request, entry.program)] ]
                        for frontier in frontiers ]
        zs = (lse([ l for l,_ in ls ]) for ls in likelihoods)
        return sum(math.exp(l - z)*u
                   for z,frontier in izip(zs,likelihoods)
                   for l,u in frontier)

    def insideOutside(self, frontiers, pseudoCounts):
        uses = self.expectedUses(frontiers)
        return FragmentGrammar(log(uses.actualVariables + pseudoCounts)
                               - log(max(uses.possibleVariables, 1.)),
                               [ (log(uses.actualUses.get(p,0.) + pseudoCounts)
                                  - log(uses.possibleUses.get(p,pseudoCounts)),
                                  t,p)
                                 for _,t,p in self.productions ])

    def jointFrontiersLikelihood(self, frontiers):
        return sum( lse([ entry.logLikelihood + self.logLikelihood(frontier.task.request, entry.program)
                          for entry in frontier ])
                    for frontier in frontiers )
    def jointFrontiersMDL(self, frontiers, CPUs = 1):
        return sum( parallelMap(CPUs, \
                                lambda frontier: max( entry.logLikelihood + self.logLikelihood(frontier.task.request, entry.program)
                                                      for entry in frontier ),
                                frontiers ) )

    def __len__(self): return len(self.productions)

    @staticmethod
    def fromGrammar(g):
        return FragmentGrammar(g.logVariable, g.productions)
    def toGrammar(self):
        return Grammar(self.logVariable, [(l,q.infer(),q)
                                          for l,t,p in self.productions
                                          for q in [defragment(p)] ])

    @property
    def primitives(self): return [ p for _,_,p in self.productions ]

    @staticmethod
    def uniform(productions):
        return FragmentGrammar(0., [(0., p.infer(),p) for p in productions ])
    def normalize(self):
        z = lse([ l for l,t,p in self.productions ] + [self.logVariable])
        return FragmentGrammar(self.logVariable - z,
                               [ (l - z,t,p) for l,t,p in self.productions ])
    def makeUniform(self):
        return FragmentGrammar(0., [(0., p.infer(),p) for _,_,p in self.productions ])

    def rescoreFrontier(self, frontier):
        return Frontier([ FrontierEntry(e.program,
                                        logPrior = self.logLikelihood(frontier.task.request, e.program),
                                        logLikelihood = e.logLikelihood)
                          for e in frontier ],
                        frontier.task)

    @staticmethod
    def induceFromFrontiers(g0, frontiers, _ = None,
                            topK = 1, pseudoCounts = 1.0, aic = 1.0, structurePenalty = 0.001, a = 0, CPUs = 1):
        originalFrontiers = frontiers
        frontiers = [frontier for frontier in frontiers if not frontier.empty ]
        eprint("Inducing a grammar from",len(frontiers),"frontiers")

        bestGrammar = FragmentGrammar.fromGrammar(g0)
        oldJoint = bestGrammar.jointFrontiersMDL(frontiers, CPUs = 1)

        # "restricted frontiers" only contain the top K according to the best grammar
        def restrictFrontiers():
            return parallelMap(CPUs, lambda f: bestGrammar.rescoreFrontier(f).topK(topK),
                               frontiers)
        restrictedFrontiers = []

        def grammarScore(g):
            g = g.makeUniform().insideOutside(restrictedFrontiers, pseudoCounts)
            likelihood = g.jointFrontiersMDL(restrictedFrontiers)
            structure = sum(fragmentSize(p) for p in g.primitives)
            score = likelihood - aic*len(g) - structurePenalty*structure
            g.clearCache()
            if invalid(score):
                # FIXME: This should never occur but it does anyway
                score = float('-inf')
            return score, g


        if aic is not POSITIVEINFINITY:
            restrictedFrontiers = restrictFrontiers()
            bestScore, _ = grammarScore(bestGrammar)
            while True:
                restrictedFrontiers = restrictFrontiers()
                fragments = [ f
                              for f in proposeFragmentsFromFrontiers(restrictedFrontiers, a)
                              if not f in bestGrammar.primitives \
                              and defragment(f) not in bestGrammar.primitives ]
                eprint("Proposed %d fragments."%len(fragments))

                candidateGrammars = [ FragmentGrammar.uniform(bestGrammar.primitives + [fragment])
                                      for fragment in fragments ]
                if not candidateGrammars:
                    break

                scoredFragments = parallelMap(CPUs, grammarScore, candidateGrammars,
                                              # Each process handles up to 100 grammars at a time, a "job"
                                              chunk = max(1,min(len(candidateGrammars)/CPUs, 100)),
                                              # maxTasks: Maximum number of jobs allocated to a process
                                              # This means that after evaluating this*chunk many grammars,
                                              # we killed the process, freeing up its memory.
                                              # In exchange we pay the cost of spawning a new process.
                                              # We should play with this number,
                                              # figuring out how big we can make it without
                                              # running out of memory.
                                              maxTasks = 5)
                newScore, newGrammar = max(scoredFragments)

                if newScore <= bestScore:
                    break
                dS = newScore - bestScore
                bestScore, bestGrammar = newScore, newGrammar
                newPrimitiveLikelihood,newType,newPrimitive = bestGrammar.productions[-1]
                expectedUses = bestGrammar.expectedUses(restrictedFrontiers).actualUses[newPrimitive]
                eprint("New primitive of type %s\t%s\t\n(score = %f; dScore = %f; <uses> = %f)"%
                       (newType,newPrimitive,newScore,dS,expectedUses))
                
                # Rewrite the frontiers in terms of the new fragment
                concretePrimitive = defragment(newPrimitive)
                bestGrammar.productions[-1] = (newPrimitiveLikelihood,
                                               concretePrimitive.tp,
                                               concretePrimitive)
                frontiers = parallelMap(CPUs,
                                        lambda frontier: RewriteFragments.rewriteFrontier(frontier, newPrimitive),
                                        frontiers)
                eprint("\t(<uses> in rewritten frontiers: %f)"%
                       (bestGrammar.expectedUses(frontiers).actualUses[concretePrimitive]))
        else:
            eprint("Skipping fragment proposals")

        if False:
            # Reestimate the parameters using the entire frontiers
            bestGrammar = bestGrammar.makeUniform().insideOutside(frontiers, pseudoCounts)
        elif True:
            # Reestimate the parameters using the best programs
            restrictedFrontiers = restrictFrontiers()
            bestGrammar = bestGrammar.makeUniform().insideOutside(restrictedFrontiers, pseudoCounts)
        else:
            # Use parameters that were found during search
            pass
            

        eprint("Old joint = %f\tNew joint = %f\n"%(oldJoint,
                                                   bestGrammar.jointFrontiersMDL(frontiers,CPUs = CPUs)))
        bestGrammar.clearCache()

        # Return all of the frontiers, which have now been rewritten to use the new fragments
        frontiers = {f.task: f for f in frontiers }
        frontiers = [ frontiers.get(f.task, f)
                      for f in originalFrontiers ]
        
        return bestGrammar.toGrammar(), frontiers

def induceGrammar(*args, **kwargs):
    with timing("Induced a grammar"):
        backend = kwargs.pop("backend","pypy")
        if backend == "pypy":
            g, newFrontiers = callCompiled(pypyInduce, *args, **kwargs)
        elif backend == "rust":
            g, newFrontiers = rustInduce(*args, **kwargs)
        else: assert False, ""
    return g, newFrontiers


def pypyInduce(*args, **kwargs):
    return FragmentGrammar.induceFromFrontiers(*args, **kwargs)

def rustInduce(g0, frontiers, _=None,
               topK=1, pseudoCounts=1.0, aic=1.0,
               structurePenalty=0.001, a=0, CPUs=1):
    import json
    import os
    import subprocess

    message = {
        "params": {
            "structure_penalty": structurePenalty,
            "pseudocounts": int(pseudoCounts+0.5),
            "topk": topK,
            "aic": aic,
            "arity": a,
        },
        "primitives": [{"name": p.name, "tp": str(t), "logp": l}
                       for l,t,p in g0.productions if p.isPrimitive ],
        "inventions": [{"expression": str(p.body), "logp": l}
                       for l,t,p in g0.productions if p.isInvented],
        "variable_logprob": g0.logVariable,
        "frontiers": [{
            "task_tp": str(f.task.request),
            "solutions": [{
                "expression": str(e.program),
                "logprior": e.logPrior,
                "loglikelihood": e.logLikelihood,
            } for e in f ],
        } for f in frontiers ],
    }

    eprint("running rust compressor")
    p = subprocess.Popen(['./rust_compressor/rust_compressor'],
                         stdin=subprocess.PIPE, stdout=subprocess.PIPE)
    json.dump(message, p.stdin)
    p.stdin.close()
    resp = json.load(p.stdout)
    if p.returncode is not None:
        raise ValueError("rust compressor failed")

    productions = [(x["logp"], p) for p, x in
                   zip((p for (_, _, p) in g0.productions if p.isPrimitive), resp["primitives"])] + \
                  [(i["logp"], Invented(Program.parse(i["expression"])))
                   for i in resp["inventions"] ]
    g = Grammar.fromProductions(productions, resp["variable_logprob"])
    newFrontiers = [Frontier(
        [FrontierEntry(Program.parse(s["expression"]), logPrior=s["logprior"], logLikelihood=s["loglikelihood"])
         for s in r["solutions"]],
        f.task) for f, r in zip(frontiers, resp["frontiers"])]
    return g, newFrontiers

if __name__ == "__main__":
    from arithmeticPrimitives import *
    from listPrimitives import *
    McCarthyPrimitives()
    f = Program.parse("(fix1 $0 (lambda (lambda (if (empty? $0) $3 ($4 ($5 $0) ($1 (cdr $0)))))))")
    p = Program.parse("(fix1 $0 (lambda (lambda (if (empty? $0) empty (cons (cdr $0) ($1 (cdr $0)))))))")
    print p
    print f
    request = arrow(tlist(tint),tlist(tlist(tint)))
    _,t,b = Matcher.match(Context.EMPTY, f, p, 2)
    print "With fragment likelihood",\
        FragmentGrammar.uniform([f] + McCarthyPrimitives()).logLikelihood(request, Abstraction(p))
    print "without fragment likelihood",\
        FragmentGrammar.uniform(McCarthyPrimitives()).logLikelihood(request, Abstraction(p))
    pp = RewriteFragments(f).rewrite(Abstraction(p))
    print pp
    print pp.infer()

    g = FragmentGrammar.fromGrammar(Grammar.uniform([defragment(f)] + McCarthyPrimitives()))
    print g
    g.logLikelihood(request,pp)
    # p = Abstraction(p)
    # for a in xrange(3):
    #     for b in xrange(3):
    #         for c in xrange(3):
    #             print pp.evaluate([])(a)(b)(c) == p.evaluate([])(a)(b)(c)
    print t
    print b
